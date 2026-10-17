"""Source map of the pages: data-lhtml-src="file:line" on the blocks of the HTML.

In a build for development (--layout, --serve, --watch), each line of a
template read by the build gets an invisible marker naming the file it is
in and its line number (private-use characters, `\\ue000<file>:<line>\\ue001`).
The markers go through Jinja and LHTML as text. After LHTML, `apply` gives
each block of the content the place of the first marker it contains (or of
a marker just before it) as `data-lhtml-src="<file>:<line>"`, and removes
the markers. The layout report and the comments on the render point to the
source with it.

The file travels in the marker rather than being stamped at the end,
because a page is not the only template it is made of: what a template
included by the page writes is written in that template. The templates
marked are those of the project (the page and what it includes from the
source directories); the theme's are not, so a block of the theme's own
base template is left unmarked rather than named as content of the page.

Where a marker goes on a line, so that LHTML reads the line as before:
- at its end in general (`= Title`, `* item`, `div::(.x)`, `img::a.png[...]`,
  `{{ box('x') }}`: the block after which it comes on its line gets it);
- before an HTML tag that ends the line (`<div>text</div>`, `line<br>`):
  LHTML reads a line ending with a block tag as structure;
- before the final `::` of an element closed on the line (`credit:: x ::`);
- at its start when the line ends with the value of a tag (`img::a.png`,
  `gap::l`, `demo::url`): the marker would become part of the value;
- nowhere on the lines that are only a closing `::`, a Jinja statement, a
  list item or title marker without text, on the lines with an LHTML comment,
  inside the Jinja blocks whose content is a value ({% set x %}...{% endset %},
  {% markdown %}, {% filter %}),
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
import os
import re

from lib import front_matter, source_scan

OPEN, CLOSE = '', ''
LEADING = ''              # written at the start of the line of the block that follows
MARKER = re.compile(f'{OPEN}([^{OPEN}{LEADING}{CLOSE}]*)({LEADING}?){CLOSE}')
ATTRIBUTE = 'data-lhtml-src'
NEAR = 'data-lhtml-near'        # the line is the one before the block, not its own

CLOSER = re.compile(r'^\s*::(?:[\w-]*\[-\])?\s*$')
JINJA_LINE = re.compile(r'^\s*(\{%.*%\}|\{#.*#\})\s*$')
# `* ` or `=(.x) ` alone: a marker would become its text
EMPTY_ITEM = re.compile(r'^\s*(\*+|=+)(\([^()\n]*\))?\s*$')
LAST_TAG = re.compile(r'([A-Za-z][\w-]*)::(\S*)\s*$')
# An HTML tag at the end of a line (LHTML: a line ending with a block tag is
# structure, it gets no <br> with line-breaks): the marker goes before it
TRAILING_TAG = re.compile(r'</?[A-Za-z][\w-]*(?:[^<>"\']|"[^"]*"|\'[^\']*\')*/?>\s*$')
# Jinja blocks whose content is a value, not text of the page: no markers
VALUE_BLOCK = re.compile(r'\{%-?\s*(?:(?:end)?(markdown|filter)\b|endset\b|set\s+[^=%]*%\})')
VOID = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source',
                  'track', 'wbr'))
WRAPPERS = frozenset(('div', 'main', 'section', 'article'))
TAG_NAME = re.compile(r'<[A-Za-z][\w-]*')         # the name of an opening tag


def marker(place, leading=False):
    """The marker of a place, `<file>:<line>`. The file travels with the
    line because a page is not the only template it is made of: what an
    included file writes is written there, not in the page that includes it.

    `leading`: the marker is written at the start of its line, before the
    block that line creates (`img::a.png`, `gap::l`), so the block that
    comes right after it is on that line."""
    return f'{OPEN}{place}{LEADING if leading else ""}{CLOSE}'


def add_markers(text, source, tags):
    """The template `text` with a marker of `<source>:<line>` on each line
    where LHTML reads it as before (see the module documentation); `tags`
    are the tags whose value ends a line (source_scan.value_tags)."""
    def marker_for(number, leading=False):
        return marker(f'{source}:{number}', leading)
    found = source_scan.zones(text)
    skipped = source_scan.multiline_lines(text, found) | _value_block_lines(text, found)
    header = front_matter.FRONT_MATTER.match(text)      # the YAML stays as it is: removed later
    skipped |= set(range(text.count('\n', 0, header.end()) + 1)) if header else set()
    offsets = source_scan.line_offsets(text)
    out = []
    for index, line in enumerate(text.split('\n')):
        number = index + 1
        if (index in skipped or not line.strip() or CLOSER.match(line)
                or JINJA_LINE.match(line) or EMPTY_ITEM.match(line)):
            out.append(line)
            continue
        stripped = line.rstrip()
        last = LAST_TAG.search(stripped)
        trailing = TRAILING_TAG.search(stripped)
        if last and last.group(1) in tags and not stripped.endswith((']', ')', '}')):
            # the line ends with the value of a tag: marker at its start, if the tag starts it
            out.append(marker_for(number, True) + line if line.lstrip().startswith(last.group(0)) else line)
        elif (stripped.endswith('::') and stripped[:-2].count('::') >= 1 and not stripped.endswith('::::')
              and not _in_zone(found, offsets[index] + len(stripped) - 2)):
            out.append(stripped[:-2] + marker_for(number) + '::' + line[len(stripped):])
        elif trailing and _is_tag_zone(found, offsets[index] + trailing.start()):
            # a line that is an opening tag takes its marker at the start,
            # before the block that tag writes: that block is on this line
            leading = trailing.start() == 0 and not stripped.startswith('</')
            out.append(line[:trailing.start()] + marker_for(number, leading) + line[trailing.start():])
        else:
            out.append(stripped + marker_for(number) + line[len(stripped):])
    return '\n'.join(out)


def _in_zone(found, position):
    return any(z.start < position < z.end for z in found)


def _is_tag_zone(found, position):
    """Whether an HTML tag of the text starts at `position` (not in code, a comment...)."""
    return any(z.start == position and z.kind == 'tag' for z in found)


def _value_block_lines(text, found):
    """0-based indices of the lines of the Jinja blocks whose content is a
    value ({% set x %}...{% endset %}, {% markdown %}, {% filter %}): a
    marker would change it."""
    lines, depth, first = set(), 0, 0
    for zone in found:
        m = zone.kind == 'jinja' and VALUE_BLOCK.match(text, zone.start)
        if not m:
            continue
        closing = text[m.start():m.end()].lstrip('{%- \t').startswith('end')
        if not closing:
            if depth == 0:
                first = text.count('\n', 0, zone.start)
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                lines.update(range(first, text.count('\n', 0, zone.end) + 1))
    return lines


def strip(text):
    """The text without markers."""
    return MARKER.sub('', text)


class _Mark(str):
    """The place `<file>:<line>` a marker names, and whether it was written
    at the start of the line of the block that follows it (see `marker`)."""

    def __new__(cls, value, leading=False):
        mark = super().__new__(cls, value)
        mark.leading = leading
        return mark


class _After(_Mark):
    """The line of a marker right after an element, on its line (raw HTML,
    the output of a macro): the line of this element."""


class _Element:
    __slots__ = ('tag', 'offset', 'items', 'first', 'texts')

    def __init__(self, tag, offset):
        self.tag, self.offset = tag, offset
        self.items = []         # in order: child _Element, or the line (int, _After) of a marker in its text
        self.texts = []
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
        self.new_line = True    # a line break since the last tag

    def feed_text(self, text):
        for line in text.split('\n')[:-1]:
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.feed(text)
        self.close()

    def _offset(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        self.new_line = False
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
        self.new_line = False
        if tag == 'body':
            self.stack = []
            return
        for k in range(len(self.stack) - 1, 0, -1):        # misnested tags: up to the open one
            if self.stack[k].tag == tag:
                del self.stack[k:]
                return

    def handle_data(self, data):
        if self.stack:
            self.stack[-1].texts.append(data)
            items = self.stack[-1].items
            for m in MARKER.finditer(data):
                after = (not self.new_line and '\n' not in data[:m.start()] and items
                         and isinstance(items[-1], _Element))
                leading = bool(m.group(2))
                items.append(_After(m.group(1)) if after else _Mark(m.group(1), leading))
        self.new_line = self.new_line or '\n' in data


def _first_markers(element):
    for item in element.items:
        line = _first_markers(item) if isinstance(item, _Element) else item
        if element.first is None and line is not None:
            element.first = line
    return element.first


def _content(root):
    """The element holding the blocks: the root, or the wrapper holding all its markers."""
    element = root
    while not any(isinstance(item, _Mark) for item in element.items):
        marked = [c for c in element.children() if c.first is not None]
        if len(marked) != 1 or marked[0].tag not in WRAPPERS or not marked[0].children():
            break
        element = marked[0]
    return element


def block_lines(html):
    """{offset of the start tag of a block: (place, exact)}: the blocks of the
    content with the place of their first marker, else of the marker right
    after them on their line - both the line of the block itself, `exact` -
    else of the marker just before them. That last marker is the line of the
    block too when it is a leading one (written at the start of the line the
    block comes from: `gap::l`, `img::a.png`); otherwise it is the line of
    what comes before, a landmark and not a position, and the report must
    not state it as one."""
    tree = _Tree(whole=not re.search(r'<body[\s>]', html, re.IGNORECASE))
    tree.feed_text(html)
    if tree.root is None:
        return {}
    _first_markers(tree.root)
    lines, pending, previous = {}, None, None
    for item in _content(tree.root).items:
        if isinstance(item, _After) and previous is not None:
            if previous.first is None:          # its own line, rather than a marker before it
                lines[previous.offset] = (str(item), True)
        elif isinstance(item, _Mark):
            pending = item
        else:
            if item.first is not None or pending is not None:
                lines[item.offset] = ((item.first, True) if item.first is not None
                                      else (pending, pending.leading))
            pending, previous = None, item
            continue
        previous = None
    return lines


def source_label(src, config_directory, source_directory=None):
    """How a source is named in the pages: its path relative to the project.

    The marker is read by an author and by their agent, so it must point at
    a file of the project - never at the machine it was built on. A source
    outside the configuration directory would give a path climbing out of
    it ('../../../Users/...'), published in every page of a --layout build:
    it is named relative to the sources instead, and by its name alone if
    it is outside them too."""
    relative = os.path.relpath(src, config_directory)
    if not relative.startswith('..'):
        return relative
    if source_directory:
        inside = os.path.relpath(src, source_directory)
        if not inside.startswith('..'):
            return inside
    return os.path.basename(src)


def apply(html):
    """The HTML of a page with data-lhtml-src="<file>:<line>" on the blocks
    of its content, and without markers. The file is the one the marker
    carries, so a block of an included template names that template. A block
    whose line is the one of a marker before it, not of a marker of its own,
    also gets data-lhtml-near: the line is where to look, not where it is."""
    if OPEN not in html:
        return html
    try:
        lines = block_lines(html)
    except Exception:           # malformed HTML: no source map, but no markers either
        return strip(html)
    for offset in sorted(lines, reverse=True):
        name_end = TAG_NAME.match(html, offset)
        if name_end:
            insert = name_end.end()
            place, exact = lines[offset]
            near = '' if exact else f' {NEAR}="1"'
            html = html[:insert] + f' {ATTRIBUTE}="{html_lib.escape(place, quote=True)}"{near}' + html[insert:]
    return strip(html)
