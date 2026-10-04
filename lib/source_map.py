"""Source map of the pages: data-src="file:line" on the blocks of the HTML.

In a build for development (--layout, --serve, --watch), each line of a
template copied into the site gets an invisible marker with its line number
(private-use characters, `\\ue000<line>\\ue001`). The markers go through Jinja
and LHTML as text. After LHTML, `apply` gives each top-level element of the
content the line of the first marker it contains (or of a marker just before
it) as `data-src="<file>:<line>"`, and removes the markers. The layout report
and the comments on the render point to the source with it.

Where a marker goes on a line, so that LHTML reads the line as before:
- at its end in general (`= Title`, `* item`, `div::(.x)`, `img::a.png[...]`);
- before the final `::` of an element closed on the line (`credit:: x ::`);
- at its start when the line ends with the value of a tag (`img::a.png`,
  `gap::l`, `demo::url`): the marker would become part of the value;
- nowhere on the lines that are only a closing `::`, a Jinja statement or
  comment, an LHTML comment, and inside multi-line Jinja tags, HTML tags,
  code and verbatim blocks, display math and <script>/<style>/<pre>.
"""
from __future__ import annotations

from html.parser import HTMLParser
import html as html_lib
import re

OPEN, CLOSE = '', ''
MARKER = re.compile(f'{OPEN}(\\d+){CLOSE}')
# LHTML tags whose text is a value (URL, file, variant), as their handler reads it
VALUE_TAGS = {'img', 'video', 'videoplay', 'link', 'include'}
URL_TAGS = {'img', 'video', 'videoplay', 'link'}

CLOSER = re.compile(r'^\s*::(?:[\w-]*\[-\])?\s*$')
JINJA_LINE = re.compile(r'^\s*(\{%.*%\}|\{#.*#\})\s*$')
LHTML_COMMENT = re.compile(r'^\s*::#')
LAST_TAG = re.compile(r'([A-Za-z][\w-]*)::(\S*)\s*$')
CODE_OPEN = re.compile(r'^\s*(?:code|verbatim)::')
RAW_BLOCK = re.compile(r'<(script|style|pre)\b', re.IGNORECASE)
TAG_OPEN = re.compile(r'<[A-Za-z][\w-]*(?:\s[^<>]*)?$')      # an HTML tag continued on the next line


def value_tags(macros=None):
    """Tags whose text is a value: the built-in ones, and the macros that are
    empty, take a URL or a variant, or render an img/video/link."""
    tags = set(VALUE_TAGS)
    for name, spec in (macros or {}).items():
        spec = spec or {}
        if spec.get('empty') or spec.get('url') or spec.get('variant') or spec.get('tag') in URL_TAGS:
            tags.add(name)
    return tags


def marker(line):
    return f'{OPEN}{line}{CLOSE}'


def _ends_open(line, start, end):
    """Whether `line` leaves a `start` ... `end` span open."""
    return line.rfind(start) > line.rfind(end)


def add_markers(text, tags=VALUE_TAGS):
    """The template `text` with a marker of its line number on each line
    where LHTML reads it as before (see the module documentation)."""
    out = []
    in_jinja = in_html = in_code = in_math = False
    raw_end = None
    for number, line in enumerate(text.split('\n'), 1):
        skip = in_jinja or in_html or in_code or in_math or raw_end is not None
        # spans that continue on the next lines
        if raw_end is not None:
            if raw_end in line.lower():
                raw_end = None
        elif (m := RAW_BLOCK.search(line)) and f'</{m.group(1).lower()}' not in line.lower():
            raw_end = f'</{m.group(1).lower()}'
            skip = True
        if in_code:
            in_code = not CLOSER.match(line)
        elif CODE_OPEN.match(line) and not line.split('::', 1)[1].rstrip().endswith('::'):
            in_code, skip = True, True
        for start, end in (('{%', '%}'), ('{#', '#}')):
            if _ends_open(line, start, end):
                in_jinja, skip = True, True
            elif in_jinja and end in line:
                in_jinja = False
        tag_open = TAG_OPEN.search(line)
        if in_html:
            in_html = '>' not in line
        elif tag_open:
            in_html, skip = True, True
        if line.count('$$') % 2:
            in_math = not in_math
            skip = True
        if skip or not line.strip() or CLOSER.match(line) or JINJA_LINE.match(line) or LHTML_COMMENT.match(line):
            out.append(line)
            continue
        stripped = line.rstrip()
        last = LAST_TAG.search(stripped)
        if last and last.group(1) in tags and not stripped.endswith((']', ')', '}')):
            # the line ends with the value of a tag: marker at its start, if the tag starts it
            out.append(marker(number) + line if line.lstrip().startswith(last.group(0)) else line)
        elif stripped.endswith('::') and stripped[:-2].count('::') >= 1 and not stripped.endswith('::::'):
            out.append(stripped[:-2] + marker(number) + '::' + line[len(stripped):])
        else:
            out.append(stripped + marker(number) + line[len(stripped):])
    return '\n'.join(out)


def strip(text):
    """The text without markers."""
    return MARKER.sub('', text)


class _Blocks(HTMLParser):
    """Top-level elements of <body> and the markers they contain (or that come
    just before them)."""

    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.depth = None           # depth under <body>; None outside <body>
        self.stack = []
        self.current = None         # start offset of the top-level element being read
        self.pending = None         # line of the last marker read outside the elements
        self.lines = {}             # start offset of a top-level element -> line of its first marker
        self.before = {}            # start offset -> line of the marker just before it
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
        if tag == 'body':
            self.depth = 0
            return
        if self.depth is None:
            return
        if self.depth == 0:
            self.current = self._offset()
            if self.pending is not None:
                self.before[self.current] = self.pending
                self.pending = None
        if tag not in self.VOID:
            self.depth += 1
        elif self.depth == 0:
            self.current = None

    def handle_endtag(self, tag):
        if self.depth is None or tag in self.VOID:
            return
        if tag == 'body':
            self.depth = None
            return
        self.depth = max(0, self.depth - 1)
        if self.depth == 0:
            self.current = None

    def handle_data(self, data):
        if self.depth is None:
            return
        for m in MARKER.finditer(data):
            if self.depth > 0 and self.current is not None:
                self.lines.setdefault(self.current, int(m.group(1)))
            else:
                self.pending = int(m.group(1))


def apply(html, source):
    """The HTML of a page with data-src="<source>:<line>" on the top-level
    elements of its body, and without markers."""
    if OPEN not in html:
        return html
    parser = _Blocks()
    if not re.search(r'<body[\s>]', html, re.IGNORECASE):
        parser.depth = 0            # a page not wrapped in a document: its elements are the blocks
    try:
        parser.feed_text(html)
    except Exception:           # malformed HTML: no source map, but no markers either
        return strip(html)
    attribute = html_lib.escape(source, quote=True)
    lines = {**parser.before, **parser.lines}       # its own marker first, else the one before it
    for offset in sorted(lines, reverse=True):
        end = re.compile(r'\s*/?>').search(html, offset)
        name_end = re.compile(r'<[A-Za-z][\w-]*').match(html, offset)
        if name_end and end:
            insert = name_end.end()
            html = html[:insert] + f' data-src="{attribute}:{lines[offset]}"' + html[insert:]
    return strip(html)
