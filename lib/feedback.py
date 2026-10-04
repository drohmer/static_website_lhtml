"""Comments on the render (--serve): a reviewer clicks a block of a page and
writes a comment; an agent (or the author) then treats them.

The comments are kept next to the configuration, in .feedback/:
- comments.jsonl: one JSON object per line {id, time, page, src, block,
  rect, comment, status}, status 'open' or 'done';
- comments.md: the same, readable, open comments first, with the file and
  line of the source of each block (data-src of the source map).

The browser side is lib/feedback.js, added to the pages served by --serve;
lib/development.py serves it and receives the comments.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import threading

DIRECTORY = '.feedback'
SCRIPT = Path(__file__).with_name('feedback.js')
URL = '/__feedback/'
MAX_COMMENT = 5000
_lock = threading.Lock()


class FeedbackError(ValueError):
    pass


def load(directory):
    path = Path(directory) / 'comments.jsonl'
    if not path.is_file():
        return []
    comments = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                comments.append(json.loads(line))
            except ValueError:
                continue
    return comments


def _save(directory, comments):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'comments.jsonl').write_text(
        ''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in comments), encoding='utf-8')
    (directory / 'comments.md').write_text(markdown(comments), encoding='utf-8')


def _text(value, limit=500):
    return str(value or '')[:limit]


def add(directory, data):
    """Record a comment sent by the browser; returns it."""
    comment = _text(data.get('comment'), MAX_COMMENT).strip()
    if not comment:
        raise FeedbackError('empty comment')
    rect = data.get('rect') or {}
    record = {'time': datetime.now().isoformat(timespec='seconds'),
              'page': _text(data.get('page')), 'src': _text(data.get('src')) or None,
              'block': _text(data.get('block'), 200),
              'rect': {k: round(float(rect.get(k, 0))) for k in ('x', 'y', 'w', 'h')},
              'comment': comment, 'status': 'open'}
    with _lock:
        comments = load(directory)
        record = {'id': max((c.get('id', 0) for c in comments), default=0) + 1, **record}
        comments.append(record)
        _save(directory, comments)
    return record


def resolve(directory, comment_id, status='done'):
    with _lock:
        comments = load(directory)
        for c in comments:
            if c.get('id') == comment_id:
                c['status'] = status
                _save(directory, comments)
                return c
    raise FeedbackError(f'no comment {comment_id}')


def markdown(comments):
    out = ['# Comments on the render', '',
           'Written on the pages served by `generate.py --serve` (💬, or the key c, then a click on a block).',
           'Treat the open ones, then set their "status" to "done" in comments.jsonl (or click their',
           'number on the page, then "Done").', '']
    for status, title in (('open', 'Open'), ('done', 'Done')):
        selected = [c for c in comments if c.get('status') == status]
        out += [f'## {title} ({len(selected)})', '']
        for c in selected:
            where = f"`{c['src']}`" if c.get('src') else 'source unknown'
            rect = c.get('rect') or {}
            out += [f"### {c['id']}. {c['page']} — {where}", '',
                    f"Block: {c.get('block') or '-'} (x {rect.get('x')}, y {rect.get('y')}, "
                    f"{rect.get('w')}×{rect.get('h')} px)", '', c['comment'], '']
    return '\n'.join(out) + '\n'


def script_tag():
    """The <script> added to the served pages."""
    return f'<script src="{URL}feedback.js" defer></script>'


def add_script(html):
    """The HTML of a page with the feedback script (before </body>)."""
    position = html.lower().rfind('</body>')
    return html + script_tag() if position < 0 else html[:position] + script_tag() + html[position:]
