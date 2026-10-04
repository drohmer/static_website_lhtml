"""Reading of the page sources as LHTML reads them.

LHTML leaves some zones of a page as they are: verbatim and code blocks
(`code::[python]` ... `code::[-]`), Jinja tags, HTML comments, <script> and
<style>, inline code, the URLs of img::/video::/link::, math and HTML tags;
it removes the LHTML comments (`::# ...`). The scanners of the generator (the
lint, the source map, the credits and the placeholders) find these zones with
the regular expressions of LHTML itself, so that they agree with it on what
is code and what is text.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from lhtml import patterns

# kinds of zones, in the order of the groups of patterns.PROTECTED_BLOCKS
KINDS = ('verbatim', 'code', 'jinja', 'comment', 'raw', 'icode', 'urltag', 'math', 'tag')
LHTML_COMMENT = 'lhtml_comment'
# zones whose text is not read as LHTML (what the lint and the credits skip)
NOT_TEXT = frozenset(('verbatim', 'code', 'comment', 'raw', 'icode', 'math', LHTML_COMMENT))

URL_TAGS = frozenset(patterns.URL_TAGS)
# the value of a tag: a URL, a file (img::a.png(.wide): the class group is not part of it)
VALUE = patterns.URL_TOKEN
LAYOUT_SET = re.compile(r'''\{%-?\s*set\s+layout\s*=\s*['"]([^'"]*)['"]\s*-?%\}''')
# Lines kept before {% extends %} by auto_wrap: blank lines, Jinja comments,
# {% set name = value %}, {% import %} / {% from ... import %}, LHTML comments
LEADING_LINE = re.compile(r'[ \t]*(?:\{%-?\s*(?:set\s+[^%\n]*=|import\s|from\s)[^\n]*?-?%\}|\{#[^\n]*?#\}'
                          r'|::#[^\n]*)?[ \t]*(?:\n|\Z)')


@dataclass(frozen=True)
class Zone:
    start: int
    end: int
    kind: str


def zones(text):
    """Zones of a source that LHTML does not read as text, in order: [Zone]."""
    found = []
    for m in patterns.PROTECTED_BLOCKS.finditer(text):
        kind = next(k for k in KINDS if m.group(k) is not None)
        found.append(Zone(m.start(), m.end(), kind))
    # LHTML comments: removed by LHTML after the zones above were protected
    free = _blank(text, found, '\x01')
    found += [Zone(m.start(), m.end(), LHTML_COMMENT) for m in patterns.COMMENT.finditer(free)]
    return sorted(found, key=lambda z: z.start)


def _blank(text, selected, fill=' '):
    """`text` with the zones `selected` replaced by `fill` (line breaks kept)."""
    out, position = [], 0
    for zone in selected:
        if zone.start < position:
            continue
        out.append(text[position:zone.start])
        out.append(re.sub(r'[^\n]', fill, text[zone.start:zone.end]))
        position = zone.end
    out.append(text[position:])
    return ''.join(out)


def mask(text, kinds=NOT_TEXT, found=None):
    """`text` with the zones of `kinds` blanked out (same length and lines):
    the text read as LHTML, for the scanners."""
    return _blank(text, [z for z in (zones(text) if found is None else found) if z.kind in kinds])


def line_offsets(text):
    """Offset of the start of each line (0-based line index)."""
    offsets = [0]
    for m in re.finditer('\n', text):
        offsets.append(m.end())
    return offsets


def multiline_lines(text, found=None):
    """0-based indices of the lines touched by a zone that spans several lines
    (a code block, a Jinja tag or an HTML tag continued on the next lines,
    display math...): its first line, the lines inside it, its last line."""
    offsets = line_offsets(text)
    lines = set()
    for zone in zones(text) if found is None else found:
        first = text.count('\n', 0, zone.start)
        last = first + text.count('\n', zone.start, zone.end)
        if last > first:
            lines.update(range(first, last + 1))
    return lines


def value_tags(macros=None):
    """Tags whose text is a value (URL, file, variant): the built-in ones, and
    the macros that are empty, take a URL or a variant, or render an
    img/video/link."""
    tags = set(URL_TAGS) | {'include'}
    for name, spec in (macros or {}).items():
        spec = spec or {}
        if spec.get('empty') or spec.get('url') or spec.get('variant') or spec.get('tag') in URL_TAGS:
            tags.add(name)
    return tags


def tag_values(text, tags):
    """(tag, value, line) of the tags `tags` followed by a value in the text
    read as LHTML (img::a.png, figure::b.jpg(.wide) -> 'b.jpg')."""
    if not tags:
        return []
    pattern = re.compile(r'(?<![\w-])(' + '|'.join(sorted(map(re.escape, tags), key=len, reverse=True))
                         + r')::(' + VALUE + r')')
    masked = mask(text)
    return [(m.group(1), m.group(2), masked.count('\n', 0, m.start()) + 1) for m in pattern.finditer(masked)]


def layout_setting(text):
    """(layout, line) of the {% set layout = '...' %} of a source (not in a
    code block or a comment), or None."""
    m = LAYOUT_SET.search(mask(text))
    return (m.group(1), text.count('\n', 0, m.start()) + 1) if m else None


def leading_settings(text):
    """The lines at the top of a page that auto_wrap keeps before
    {% extends %}: blank lines, comments, {% set %} and {% import %}."""
    position = 0
    while position < len(text) and (m := LEADING_LINE.match(text, position)) and m.end() > position:
        position = m.end()
    return text[:position]
