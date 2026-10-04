"""Source map of the pages: data-lhtml-src="file:line" on the blocks of the HTML.

In a build for development (--layout, --serve, --watch), each line of a
template copied into the site gets an invisible marker with its line number
(private-use characters, `\\ue000<line>\\ue001`). The markers go through Jinja
and LHTML as text. After LHTML, `apply` gives each block of the content the
line of the first marker it contains (or of a marker just before it) as
`data-lhtml-src="<file>:<line>"`, and removes the markers. The layout report
and the comments on the render point to the source with it.

Where a marker goes on a line, so that LHTML reads the line as before:
- at its end in general (`= Title`, `* item`, `div::(.x)`, `img::a.png[...]`);
- before the final `::` of an element closed on the line (`credit:: x ::`);
- at its start when the line ends with the value of a tag (`img::a.png`,
  `gap::l`, `demo::url`): the marker would become part of the value;
- nowhere on the lines that are only a closing `::`, a Jinja statement, a
  list item or title marker without text, on the lines with an LHTML comment,
  and on the lines touched by a zone that LHTML keeps as it is and that spans
  several lines (code and verbatim blocks, Jinja and HTML tags, math, <script>,
  HTML comments: lib/source_scan.py).

The blocks are the children of the element holding the content: <body>, or
the wrapper of the theme (webpage-frame: #main-content-centered) when all the
markers are inside one <div>, <main>, <section> or <article>.
"""
from __future__ import annotations

from html.parser import HTMLParser
import html as html_lib
import re

from lib import source_scan

OPEN, CLOSE = '', ''
MARKER = re.compile(f'{OPEN}(\\d+){CLOSE}')
ATTRIBUTE = 'data-lhtml-src'

CLOSER = re.compile(r'^\s*::(?:[\w-]*\[-\])?\s*$')
JINJA_LINE = re.compile(r'^\s*(\{%.*%\}|\{#.*#\})\s*$')
EMPTY_ITEM = re.compile(r'^\s*(\*+|=+)\s*$')            # `* ` alone: a marker would become its text
LAST_TAG = re.compile(r'([A-Za-z][\w-]*)::(\S*)\s*$')
VOID = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source',
                  'track', 'wbr'))
WRAPPERS = frozenset(('div', 'main', 'section', 'article'))


def marker(line):
    return f'{OPEN}{line}{CLOSE}'


def add_markers(text, tags=source_scan.value_tags()):
    """The template `text` with a marker of its line number on each line
    where LHTML reads it as before (see the module documentation)."""
    found = source_scan.zones(text)
    skipped = source_scan.multiline_lines(text, found)
    offsets = source_scan.line_offsets(text)
    commented = {text.count('\n', 0, z.start) for z in found if z.kind == source_scan.LHTML_COMMENT}
    out = []
    for index, line in enumerate(text.split('\n')):
        number = index + 1
        if (index in skipped or index in commented or not line.strip() or CLOSER.match(line)
                or JINJA_LINE.match(line) or EMPTY_ITEM.match(line)):
            out.append(line)
            continue
        stripped = line.rstrip()
        last = LAST_TAG.search(stripped)
        if last and last.group(1) in tags and not stripped.endswith((']', ')', '}')):
            # the line ends with the value of a tag: marker at its start, if the tag starts it
            out.append(marker(number) + line if line.lstrip().startswith(last.group(0)) else line)
        elif (stripped.endswith('::') and stripped[:-2].count('::') >= 1 and not stripped.endswith('::::')
              and not _in_zone(found, offsets[index] + len(stripped) - 2)):
            out.append(stripped[:-2] + marker(number) + '::' + line[len(stripped):])
        else:
            out.append(stripped + marker(number) + line[len(stripped):])
    return '\n'.join(out)


def _in_zone(found, position):
    return any(z.start < position < z.end for z in found)


def strip(text):
    """The text without markers."""
    return MARKER.sub('', text)


class _Element:
    __slots__ = ('tag', 'offset', 'items', 'first')

    def __init__(self, tag, offset):
        self.tag, self.offset = tag, offset
        self.items = []         # in order: child _Element, or the line (int) of a marker in its text
        self.first = None       # line of the first marker inside it

    def children(self):
        return [item for item in self.items if isinstance(item, _Element)]


class _Tree(HTMLParser):
    """The elements of a page with the markers they contain (from <body>, or
    the whole page when it has no <body>)."""

    def __init__(self, whole):
        super().__init__(convert_charrefs=False)
        self.root = _Element('', 0) if whole else None
        self.stack = [self.root] if whole else []
        self.offsets = [0]

    def feed_text(self, text):
        for line in text.split('\n')[:-1]:
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.feed(text)
        self.close()

    def _offset(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag == 'body' and self.root is None:
            self.root = _Element('body', self._offset())
            self.stack = [self.root]
            return
        if not self.stack:
            return
        element = _Element(tag, self._offset())
        self.stack[-1].items.append(element)
        if tag not in VOID:
            self.stack.append(element)

    def handle_endtag(self, tag):
        if tag == 'body':
            self.stack = []
            return
        for k in range(len(self.stack) - 1, 0, -1):        # misnested tags: up to the open one
            if self.stack[k].tag == tag:
                del self.stack[k:]
                return

    def handle_data(self, data):
        if self.stack:
            self.stack[-1].items.extend(int(m.group(1)) for m in MARKER.finditer(data))


def _first_markers(element):
    for item in element.items:
        line = _first_markers(item) if isinstance(item, _Element) else item
        if element.first is None and line is not None:
            element.first = line
    return element.first


def _content(root):
    """The element holding the blocks: the root, or the wrapper holding all its markers."""
    element = root
    while not any(isinstance(item, int) for item in element.items):
        marked = [c for c in element.children() if c.first is not None]
        if len(marked) != 1 or marked[0].tag not in WRAPPERS or not marked[0].children():
            break
        element = marked[0]
    return element


def block_lines(html):
    """{offset of the start tag of a block: line}: the blocks of the content
    with the line of their first marker, or of the marker just before them."""
    tree = _Tree(whole=not re.search(r'<body[\s>]', html, re.IGNORECASE))
    tree.feed_text(html)
    if tree.root is None:
        return {}
    _first_markers(tree.root)
    lines, pending = {}, None
    for item in _content(tree.root).items:
        if isinstance(item, int):
            pending = item
        elif item.first is not None or pending is not None:
            lines[item.offset] = item.first if item.first is not None else pending
            pending = None
    return lines


def apply(html, source):
    """The HTML of a page with data-lhtml-src="<source>:<line>" on the blocks
    of its content, and without markers."""
    if OPEN not in html:
        return html
    try:
        lines = block_lines(html)
    except Exception:           # malformed HTML: no source map, but no markers either
        return strip(html)
    attribute = html_lib.escape(source, quote=True)
    for offset in sorted(lines, reverse=True):
        name_end = re.compile(r'<[A-Za-z][\w-]*').match(html, offset)
        if name_end:
            insert = name_end.end()
            html = html[:insert] + f' {ATTRIBUTE}="{attribute}:{lines[offset]}"' + html[insert:]
    return strip(html)
