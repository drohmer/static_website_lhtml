"""Reading of the page sources as LHTML reads them.

LHTML leaves some zones of a page as they are: code blocks
(`code::[python]` ... `code::[-]`), Jinja tags, HTML comments, <script> and
<style>, inline code, the URLs of img::/video::/link::, math and HTML tags.
The scanners of the generator (the
lint, the source map, the credits and the placeholders) find these zones with
lhtml.zones, the patterns LHTML parses with, so that they agree with it on
what is code and what is text. A Markdown page (lhtml_site/markdown_page.py) has its
own code blocks, fenced by ``` or ~~~; its other zones are those of LHTML.

The scanners of an LHTML page read its document tree (`document`,
lhtml.parse on the template before Jinja, which LHTML keeps opaque): the
headings and the title, the media files and the planned figures of the
credits, the styles, spacers and blocks of the lint.
What stays on the text: a Markdown page, the patterns of the lint (words),
the {% set %} of a page (Jinja), the markers of the source map.
"""
from __future__ import annotations

from functools import cached_property
import re

import lhtml

from lhtml_site import front_matter

# kinds of zones (lhtml.Zone)
KINDS = ('code', 'jinja', 'comment', 'raw', 'inline_code', 'url', 'math', 'tag')
# zones whose text is not read as LHTML (what the lint and the credits skip)
NOT_TEXT = frozenset(('code', 'comment', 'raw', 'inline_code', 'math'))

URL_TAGS = frozenset(lhtml.URL_TAGS)
# A Markdown page: a fenced code block is its `code` zone
MARKDOWN_CODE = re.compile(r'(?m:^[ \t]{0,3}(?P<mark>(?P<fc>[`~])(?P=fc){2,})[^\n]*\n.*?'
                           r'(?:^[ \t]{0,3}(?P=mark)(?P=fc)*[ \t]*$|\Z))', re.DOTALL)
CODE = {'lhtml': None, 'markdown': MARKDOWN_CODE}
Zone = lhtml.Zone
LAYOUT_SET = re.compile(r'''\{%-?\s*set\s+layout\s*=\s*['"]([^'"]*)['"]\s*-?%\}''')
# Lines kept before {% extends %} by auto_wrap: blank lines, Jinja comments,
# {% set name = value %}, {% import %} / {% from ... import %};
# one tag per line (`{% set n = 2 %}{% if n %}` stays in the content)
LEADING_LINE = re.compile(r'[ \t]*(?:\{%-?\s*(?:set\s+[^%\n]*=|import\s|from\s)(?:[^%\n]|%(?!\}))*%\}'
                          r'|\{#(?:[^#\n]|#(?!\}))*#\})?[ \t]*(?:\n|\Z)')


def zones(text, markup='lhtml'):
    """Zones of a source that its markup does not read as text, in order: [Zone]."""
    header = front_matter.FRONT_MATTER.match(text)      # the settings of the page, not its text
    found = [Zone(0, header.end(), 'comment')] if header else []
    return found + lhtml.zones(text, code=CODE[markup or 'lhtml'], start=header.end() if header else 0)


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
    lines = set()
    for zone in zones(text) if found is None else found:
        first = text.count('\n', 0, zone.start)
        last = first + text.count('\n', zone.start, zone.end)
        if last > first:
            lines.update(range(first, last + 1))
    return lines


class Scan:
    """A source read once by all the scanners: its zones and the text read as
    its markup reads it ('lhtml', 'markdown')."""

    def __init__(self, text, markup='lhtml'):
        self.text = text
        self.markup = markup or 'lhtml'

    @cached_property
    def zones(self):
        return zones(self.text, self.markup)

    @cached_property
    def masked(self):
        return mask(self.text, found=self.zones)

    def document(self, macros=None):
        """The LHTML document tree of the text (lhtml.parse, with the macros
        of the design), read once for the scanners that give the same macros;
        None when LHTML refuses the text (`refusal`: the build reports it when
        it renders the page). Its problems are not warned: the run of the
        page warns."""
        documents = self.__dict__.setdefault('_documents', {})
        key = repr(sorted((macros or {}).items()))
        if key not in documents:
            try:
                documents[key] = lhtml.parse(self.text, macros=macros or None, warn=False)
            except lhtml.LHTMLError as error:
                documents[key] = error
        found = documents[key]
        return None if isinstance(found, lhtml.LHTMLError) else found

    def refusal(self, macros=None):
        """Why LHTML refuses the text (an LHTMLError), or None."""
        self.document(macros)
        found = self._documents[repr(sorted((macros or {}).items()))]
        return found if isinstance(found, lhtml.LHTMLError) else None


def document(source, macros=None):
    """The LHTML document tree of a source (a text or a Scan): Scan.document."""
    return scan(source).document(macros)


def lhtml_headings(source, macros=None):
    """The headings of an LHTML page, those of its document tree: (start,
    end, level, attributes as written, title as written). A page that LHTML
    refuses has none here: its run reports why."""
    tree = document(source, macros)
    text = scan(source).text
    found = []
    for node in tree.walk() if tree else ():
        if node.kind == 'Heading':
            start, end = node.span
            title = node.children[0].span[0] if node.children else end
            found.append((start, end, node.level, node.parentheses, text[title:end]))
    return found


def scan(source):
    """The Scan of a source (a text, or already a Scan)."""
    return source if isinstance(source, Scan) else Scan(source)


def find(pattern, source):
    """The matches of `pattern` in the text read as LHTML (a match inside a
    code block or a comment is not one); their spans are those of the text:
    source.text[m.start(1):m.end(1)] is a group as written."""
    return list(pattern.finditer(scan(source).masked))


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


def tag_values(source, tags):
    """(tag, value, line) of the tags `tags` followed by a value in the text
    read as LHTML (img::a.png, figure::b.jpg(.wide) -> 'b.jpg')."""
    if not tags:
        return []
    text = scan(source).text
    header = front_matter.FRONT_MATTER.match(text)
    found = lhtml.zones(text, url_tags=tags, code=CODE[scan(source).markup], start=header.end() if header else 0)
    return [(z.tag, z.value, text.count('\n', 0, z.start) + 1) for z in found if z.kind == 'url']


def layout_setting(source):
    """(layout, line, offset) of the {% set layout = '...' %} of a source (not
    in a code block or a comment), or None."""
    source = scan(source)
    m = LAYOUT_SET.search(source.masked)
    return (m.group(1), source.text.count('\n', 0, m.start()) + 1, m.start()) if m else None


def leading_settings(text):
    """The lines at the top of a page that auto_wrap keeps before
    {% extends %}: blank lines, comments, {% set %} and {% import %}."""
    position = 0
    while position < len(text) and (m := LEADING_LINE.match(text, position)) and m.end() > position:
        position = m.end()
    return text[:position]
