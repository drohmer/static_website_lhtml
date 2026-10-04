"""Comments on the render (--serve): a reviewer clicks a block of a page and
writes a comment; an agent (or the author) then treats them.

The comments are kept next to the configuration, in .feedback/:
- comments.jsonl: one JSON object per line {id, time, page, src, block,
  rect, comment, status}, status 'open' or 'done';
- comments.md: the same, readable, open comments first, with the file and
  line of the source of each block (data-lhtml-src of the source map).

The browser side is lib/feedback.js, added to the pages served by --serve;
lib/development.py serves it and receives the comments.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import math
import os
import tempfile
import threading

DIRECTORY = '.feedback'
SCRIPT = Path(__file__).with_name('feedback.js')
URL = '/__feedback/'
MAX_COMMENT = 5000
_lock = threading.Lock()


class FeedbackError(ValueError):
    pass


def load(directory):
    with _lock:
        return _load(directory)


def _load(directory):
    path = Path(directory) / 'comments.jsonl'
    if not path.is_file():
        return []
    comments = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():   # edited by hand
        if line.strip():
            try:
                comment = json.loads(line)
            except ValueError:
                continue
            if isinstance(comment, dict):
                comments.append(comment)
    return comments


def _write(path, text):
    """Write a file at once (a reader never sees half of it)."""
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as fid:
        fid.write(text)
    os.replace(fid.name, path)


def _save(directory, comments):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    _write(directory / 'comments.jsonl', ''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in comments))
    _write(directory / 'comments.md', markdown(comments))


def refresh(directory):
    """Write comments.md again from comments.jsonl when the latter was edited
    by hand (status done, a comment removed) since comments.md was written."""
    directory = Path(directory)
    source, target = directory / 'comments.jsonl', directory / 'comments.md'
    with _lock:
        if source.is_file() and (not target.is_file() or target.stat().st_mtime_ns <= source.stat().st_mtime_ns):
            _write(target, markdown(_load(directory)))


def _text(value, limit=500):
    return str(value or '')[:limit]


def _coordinate(value):
    """A coordinate of the rectangle of a block (0 when it is not a finite number)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0
    return round(value) if math.isfinite(value) else 0


def add(directory, data):
    """Record a comment sent by the browser; returns it."""
    comment = _text(data.get('comment'), MAX_COMMENT).strip()
    if not comment:
        raise FeedbackError('empty comment')
    rect = data.get('rect')
    rect = rect if isinstance(rect, dict) else {}
    record = {'time': datetime.now().isoformat(timespec='seconds'),
              'page': _text(data.get('page')), 'src': _text(data.get('src')) or None,
              'block': _text(data.get('block'), 200),
              'rect': {k: _coordinate(rect.get(k)) for k in ('x', 'y', 'w', 'h')},
              'comment': comment, 'status': 'open'}
    with _lock:
        comments = _load(directory)
        record = {'id': max((c.get('id', 0) for c in comments if isinstance(c.get('id'), int)), default=0) + 1,
                  **record}
        comments.append(record)
        _save(directory, comments)
    return record


def resolve(directory, comment_id, status='done'):
    with _lock:
        comments = _load(directory)
        for c in comments:
            if c.get('id') == comment_id:
                c['status'] = status
                _save(directory, comments)
                return c
    raise FeedbackError(f'no comment {comment_id}')


def markdown(comments):
    out = ['# Comments on the render', '',
           'Written on the pages served by `generate.py --serve` (💬, or the key c, then a click on a block).',
           'Treat the open ones, then click their number on the page, then "Done" (or set their "status"',
           'to "done" in comments.jsonl: this file is written again when a page of --serve is loaded).', '']
    for status, title in (('open', 'Open'), ('done', 'Done')):
        selected = [c for c in comments if (c.get('status') == 'done') == (status == 'done')]
        out += [f'## {title} ({len(selected)})', '']
        for c in selected:          # the fields may be missing or of any type (comments.jsonl edited by hand)
            where = f"`{c['src']}`" if c.get('src') else 'source unknown'
            rect = c.get('rect') if isinstance(c.get('rect'), dict) else {}
            out += [f"### {c.get('id', '?')}. {c.get('page') or 'page unknown'} — {where}", '',
                    f"Block: {c.get('block') or '-'} (x {rect.get('x')}, y {rect.get('y')}, "
                    f"{rect.get('w')}×{rect.get('h')} px)", '', str(c.get('comment') or ''), '']
    return '\n'.join(out) + '\n'


def script_tag():
    """The <script> added to the served pages."""
    return f'<script src="{URL}feedback.js" defer></script>'


def add_script(html):
    """The HTML of a page with the feedback script (before </body>)."""
    position = html.lower().rfind('</body>')
    return html + script_tag() if position < 0 else html[:position] + script_tag() + html[position:]
