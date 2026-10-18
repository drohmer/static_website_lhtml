"""A page written in Markdown (index.md.j2): its content converted to HTML.

The author names the markup of a page by its file, `index.md.j2` for
Markdown and `index.html.j2` for LHTML: the generator never guesses it.
Jinja runs first either way. The theme wraps a Markdown page as it wraps
an LHTML one (lib/wrap.py), with its content inside the Jinja filter
`markdown_page`, so that the conversion reads the content alone and never
the HTML of the theme around it; LHTML does not read the page.

CommonMark (markdown-it-py), with tables and strikethrough, raw HTML kept,
and a fenced code block highlighted as LHTML highlights `code::[python]`
(the same HTML, which the theme styles). Two additions:
- the mathematics `\\(...\\)` and `\\[...\\]` is kept as written for
  MathJax (CommonMark reads `\\(` as an escaped `(` and `_` as emphasis);
- `# Title {: #id}` gives the heading its id (lib/headings.py writes them;
  `{#id}` would be a Jinja comment), as in kramdown and Python-Markdown.
The macros of the design (`gap::`) are LHTML's: a Markdown page uses the
macros of Jinja.
"""
import html
import re

import lhtml
from markdown_it import MarkdownIt

# A fence: ``` or ~~~, closed by a run of the same character at least as long
FENCE = (r'(?m:^[ \t]{0,3}(?P<mark>(?P<fc>[`~])(?P=fc){2,})[^\n]*\n.*?'
         r'(?:^[ \t]{0,3}(?P=mark)(?P=fc)*[ \t]*$|\Z))')
# Code is read first, so that the mathematics inside it stays code; nor is a
# URL (a link destination, an autolink, a reference) mathematics: `\(` is
# how a URL writes a parenthesis
_CODE_OR_MATH = re.compile(
    r'(?P<fence>' + FENCE + r')'
    r'|(?P<icode>(?P<ticks>`+)[^`].*?(?P=ticks))'
    r'|(?P<url>\]\((?:[^()\s]|\\[()]|\([^()\s]*\))*|<[a-zA-Z][\w+.-]*:[^\s<>]*>'
    r'|(?m:^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*\S+))'
    r'|(?P<math>\\\[.*?\\\]|\\\(.*?\\\))',
    re.DOTALL)
_HEADING_ID = re.compile(r'\s*\{:\s*#([^\s}]+)\s*\}\s*$')
_KEPT = '\ue100{}\ue101'
_KEPT_BACK = re.compile('\ue100(\\d+)\ue101')
_CODE_ELEMENT = re.compile(r'<code\b[^>]*>.*?</code>', re.DOTALL)


def _protect(text):
    """`text` with its mathematics replaced by placeholders, and what they hide."""
    kept = []

    def keep(m):
        if m.group('math') is None:
            return m.group(0)
        kept.append(m.group(0))
        return _KEPT.format(len(kept) - 1)
    return _CODE_OR_MATH.sub(keep, text), kept


def _restore(html_text, kept):
    """The mathematics back, as written; escaped where it is code (an
    indented code block, which _protect cannot tell from text)."""
    def restore(text, escape):
        return _KEPT_BACK.sub(lambda m: html.escape(kept[int(m.group(1))], quote=False) if escape
                              else kept[int(m.group(1))], text)
    parts, position = [], 0
    for m in _CODE_ELEMENT.finditer(html_text):
        parts += [restore(html_text[position:m.start()], False), restore(m.group(0), True)]
        position = m.end()
    parts.append(restore(html_text[position:], False))
    return ''.join(parts)


def _heading_ids(state):
    """`# Title {: #id}`: the id of the heading, removed from its text."""
    tokens = state.tokens
    for k, token in enumerate(tokens[:-1]):
        if token.type != 'heading_open':
            continue
        inline = tokens[k + 1]
        m = _HEADING_ID.search(inline.content)
        if m and inline.children:
            token.attrSet('id', m.group(1))
            inline.content = inline.content[:m.start()]
            last = inline.children[-1]
            if last.type == 'text':
                last.content = _HEADING_ID.sub('', last.content)


def _fence(self, tokens, k, options, env):
    token = tokens[k]
    language = token.info.split(maxsplit=1)[0] if token.info.strip() else ''
    return lhtml.highlight(token.content, language)


_parser = MarkdownIt('commonmark', {'html': True}).enable(['table', 'strikethrough'])
_parser.core.ruler.push('heading_ids', _heading_ids)
_parser.add_render_rule('fence', _fence)


def convert(text):
    """The HTML of a Markdown text."""
    protected, kept = _protect(text)
    return _restore(_parser.render(protected), kept)


def plain(text):
    """The text of a line of Markdown without its marks (`Hello *world*` ->
    `Hello world`, the mathematics as written): a title as the menu,
    <title> and the ids read it."""
    protected, kept = _protect(text)
    rendered = re.sub(r'<[^>]*>', '', _parser.renderInline(protected))
    return _KEPT_BACK.sub(lambda m: kept[int(m.group(1))], html.unescape(rendered)).strip()
