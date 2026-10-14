"""Persistent source anchors (agent extension).

Each line of a source receives an anchor kept in .source-map/identities.json,
so that a block keeps its identity across edits. The ledger lives outside
.layout: rebuilding reports must not reset identities. Ambiguous replacements
receive new anchors rather than pretending to be tracked.
"""
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
import html as html_lib
import json
import os
import re
import uuid

from lib import source_map, source_scan
from lib.source_map import MARKER, _Tree, _After, _Element, _content, _first_markers, strip


class SourceRegistry:
    def __init__(self, directory, tags):
        self.directory = Path(directory).resolve()
        self.path = self.directory / '.source-map' / 'identities.json'
        self.tags = tags
        try:
            value = json.loads(self.path.read_text())
            self.files = value.get('files', {}) if value.get('schema_version') == 1 else {}
        except (OSError, ValueError):
            self.files = {}
        self.tokens = {}
        self.prepared = {}

    def label(self, path):
        return os.path.relpath(Path(path).resolve(), self.directory)

    def instrument(self, text, path, original_text=None):
        label = self.label(path)
        if (label, text) in self.prepared:
            return self.prepared[label, text]
        original_text = text if original_text is None else original_text
        offset = original_text.find(text)
        line_offset = original_text.count('\n', 0, max(0, offset))
        lines = original_text.split('\n')
        old = self.files.get(label, [])
        previous = [row['text'] for row in old]
        assigned, consumed = {}, set()
        matcher = SequenceMatcher(None, previous, lines, autojunk=False)
        # Unchanged anchors survive insertions. Unique moved lines survive reordering.
        for tag, a, b, c, d in matcher.get_opcodes():
            if tag == 'equal':
                for i, j in zip(range(a, b), range(c, d)):
                    assigned[j] = (old[i]['id'], 'exact')
                    consumed.add(i)
        unused_old = defaultdict(list)
        unused_new = defaultdict(list)
        for i, line in enumerate(previous):
            if i not in consumed:
                unused_old[line].append(i)
        for j, line in enumerate(lines):
            if j not in assigned:
                unused_new[line].append(j)
        for text_value, indices in unused_new.items():
            candidates = unused_old.get(text_value, [])
            if text_value.strip() and len(indices) == len(candidates) == 1:
                i, j = candidates[0], indices[0]
                assigned[j] = (old[i]['id'], 'moved_exact')
                consumed.add(i)
        # A one-to-one edit in an aligned replacement keeps its anchor. Larger,
        # ambiguous replacements are deliberately not matched by line number.
        for tag, a, b, c, d in matcher.get_opcodes():
            if tag != 'replace':
                continue
            remaining_old = [i for i in range(a, b) if i not in consumed]
            remaining_new = [j for j in range(c, d) if j not in assigned]
            if len(remaining_old) == len(remaining_new) == 1:
                i, j = remaining_old[0], remaining_new[0]
                assigned[j] = (old[i]['id'], 'context_edit')
                consumed.add(i)
        # Unique reciprocal similarity also handles an edit combined with an
        # insertion/move. Ties are rejected; never infer identity from position.
        unmatched_old = [i for i, line in enumerate(previous) if i not in consumed and line.strip()]
        unmatched_new = [j for j, line in enumerate(lines) if j not in assigned and line.strip()]
        scores = {(i, j): SequenceMatcher(None, previous[i], lines[j], autojunk=False).ratio()
                  for i in unmatched_old for j in unmatched_new}
        def best(candidates):
            ordered = sorted(candidates, reverse=True)
            if not ordered or ordered[0][0] < 0.65:
                return None
            if len(ordered) > 1 and ordered[0][0] - ordered[1][0] < 0.12:
                return None
            return ordered[0][1]
        for j in unmatched_new:
            i = best([(scores[i, j], i) for i in unmatched_old])
            if i is not None and best([(scores[i, k], k) for k in unmatched_new]) == j:
                assigned[j] = (old[i]['id'], 'unique_similarity')
                consumed.add(i)
        ranges = {}
        for zone in source_scan.zones(original_text):
            if zone.kind in ('code', 'verbatim', 'math', 'raw', 'tag'):
                start = original_text.count('\n', 0, zone.start) + 1
                ranges[start] = original_text.count('\n', 0, zone.end) + 1
        rows = []
        line_tokens = {}
        for j, line in enumerate(lines):
            identity, method = assigned.get(j, (uuid.uuid4().hex, 'new'))
            rows.append({'text': line, 'id': identity})
            token = len(self.tokens) + 1
            self.tokens[token] = {'file': label, 'line': j + 1, 'anchor': identity,
                                  'matching': method, 'end_line': ranges.get(j + 1, j + 1)}
            line_tokens[j + 1] = token
        self.files[label] = rows
        result = source_map.add_markers(text, self.tags, marker_for=lambda line: source_map.marker(line_tokens[line + line_offset]), mark_protected=True)
        self.prepared[label, text] = result
        return result

    def line_anchor(self, path, line):
        rows = self.files.get(self.label(path), [])
        return rows[line - 1]['id'] if line and 0 < line <= len(rows) else None

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'schema_version': 1, 'files': self.files}, ensure_ascii=False))
        temporary.replace(self.path)


def apply_provenance(html, registry):
    """Annotate nested content elements with stable anchors and observed ranges."""
    tree = _Tree(whole=not re.search(r'<body[\s>]', html, re.IGNORECASE))
    tree.feed_text(html)
    if tree.root is None:
        return strip(html)
    _first_markers(tree.root)
    annotations, counts = {}, defaultdict(int)

    def tokens_of(element):
        tokens = []
        for item in element.items:
            tokens.extend(tokens_of(item) if isinstance(item, _Element) else [int(item)])
        return tokens

    def visit(parent):
        pending, previous = None, None
        children = []
        for item in parent.items:
            if isinstance(item, _After) and previous is not None and previous.first is None:
                annotations[previous.offset] = (previous, int(item))
            elif isinstance(item, int):
                pending = int(item)
            else:
                token = item.first if item.first is not None else pending
                if token in registry.tokens:
                    annotations[item.offset] = (item, int(token))
                children.append(item)
                pending, previous = None, item
                continue
            previous = None
        for child in children:
            visit(child)

    visit(_content(tree.root))
    inserts = {}
    for offset, (element, token) in sorted(annotations.items()):
        location = registry.tokens.get(token)
        if not location:
            continue
        groups = defaultdict(list)
        for t in [token, *tokens_of(element)]:
            if t in registry.tokens:
                row = registry.tokens[t]
                groups[row['file']].extend([row['line'], row.get('end_line', row['line'])])
        ranges = [{'file': file, 'line': min(lines), 'end_line': max(lines),
                   'range_kind': 'observed_content'} for file, lines in groups.items()]
        base = location['anchor'] + ':' + element.tag
        counts[base] += 1
        identity = base + ':' + str(counts[base])
        attrs = {'data-lhtml-src': f"{location['file']}:{location['line']}",
                 'data-lhtml-id': identity,
                 'data-lhtml-provenance': json.dumps({'ranges': ranges,
                    'matching': location['matching'], 'anchor': location['anchor']}, ensure_ascii=False)}
        inserts[offset] = ''.join(f' {key}="{html_lib.escape(value, quote=True)}"' for key, value in attrs.items())
    # Text directly in the content wrapper has no element to annotate. Store
    # its provenance on that wrapper without introducing layout-changing spans.
    content = _content(tree.root)
    free_text = []
    for text in content.texts:
        matches = list(MARKER.finditer(text))
        value = ' '.join(strip(text).split())
        if not value or not matches:
            continue
        location = registry.tokens.get(int(matches[0].group(1)))
        if not location:
            continue
        observed = [registry.tokens[int(m.group(1))] for m in matches if int(m.group(1)) in registry.tokens]
        free_text.append({'text': value, 'source': f"{location['file']}:{location['line']}",
            'stable_id': location['anchor'] + ':text:' + str(sum(1 for r in free_text
                if r['provenance']['anchor'] == location['anchor']) + 1),
            'provenance': {'anchor': location['anchor'], 'matching': location['matching'],
                'ranges': [{'file': location['file'], 'line': location['line'],
                    'end_line': max(r.get('end_line', r['line']) for r in observed),
                    'range_kind': 'observed_content'}]}})
    if free_text and content.tag:
        inserts[content.offset] = inserts.get(content.offset, '') + ' data-lhtml-free-text="' + html_lib.escape(
            json.dumps(free_text, ensure_ascii=False), quote=True) + '"'
    for offset in sorted(inserts, reverse=True):
        name_end = re.compile(r'<[A-Za-z][\w-]*').match(html, offset)
        if name_end:
            pos = name_end.end()
            html = html[:pos] + inserts[offset] + html[pos:]
    return strip(html)
