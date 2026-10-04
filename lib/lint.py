"""Design lint: values written by hand in a page that the design provides.

A slide placed with coordinates, spacers in pixels or font sizes in percent
works, but it drifts from the rest of the deck, and an LLM editing it keeps
adding pixels. The lint reads the source of each page and reports these
values with the layout or macro of the design that replaces them:

    03_squelette/03_fk/index.html.j2:12: position: position:fixed; top:150px
        -> a layout ({% set layout = 'side' %} with media::) or aside::

The number of findings of a page is its style debt (`--lint`, the build log
and the layout report give it).
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from lib import source_scan

EXTENDS = re.compile(r'\{%-?\s*extends\s')
BLOCK = re.compile(r'\{%-?\s*(end)?block\b')
STYLE = re.compile(r'([A-Za-z][\w-]*::(?:\([^()\n]*\))?[^\s\[]*)?\[([^\[\]\n]*:[^\[\]\n]*)\]|style="([^"]*)"')
RAW_IFRAME = re.compile(r'<iframe\b[^>]*style=')
SIZE_MACROS = ('small', 'tiny', 'large')     # macros of a font size (credit:: is also gray)
OFFSET_MACROS = ('aside',)                 # their documented offsets: aside::[top:400px;]
SPACER = re.compile(r'^\s*(?:div)?::\[\s*height:\s*([\d.]+)px;?\s*\]::?\s*$')
PX = re.compile(r'^\s*([\d.]+)px\s*$')
PERCENT = re.compile(r'^\s*([\d.]+)%\s*$')


@dataclass
class Finding:
    line: int           # 1-based line of the source
    kind: str           # position, spacer, font-size, offset, flex, align, color, layout
    text: str           # what was written
    advice: str         # what replaces it

    def as_dict(self):
        return {'line': self.line, 'kind': self.kind, 'text': self.text, 'advice': self.advice}


def _px_tokens(tokens):
    """{'s': 25.0, ...} for the tokens in px of a group (space)."""
    return {name: float(m.group(1)) for name, value in (tokens or {}).items()
            if isinstance(value, str) and (m := PX.match(value))}


def _nearest(value, candidates):
    return min(candidates, key=lambda name: abs(candidates[name] - value)) if candidates else None


def _layout_applies(source, offset):
    """Whether the {% set layout %} at `offset` of a page is seen by the theme:
    in the settings at the top of the page (auto_wrap puts them before its
    {% extends %}), or, in a page that writes its own {% extends %}, outside
    its {% block %}."""
    leading = source_scan.leading_settings(source.text)
    if offset < len(leading):
        return True
    masked = source.masked
    if not EXTENDS.search(masked):
        return False
    depth = 0
    for m in BLOCK.finditer(masked, 0, offset):
        depth += -1 if m.group(1) else 1
    return depth <= 0


class Linter:
    """Lint of the pages for a design (design.load_design)."""

    def __init__(self, design):
        self.macros = set(design.get('macros') or {})
        self.layouts = set(design.get('layouts') or {})
        tokens = design.get('tokens') or {}
        self.spaces = _px_tokens(tokens.get('space'))
        self.fonts = {name: float(m.group(1)) for name, value in (tokens.get('font') or {}).items()
                      if name in SIZE_MACROS and name in self.macros
                      and isinstance(value, str) and (m := PERCENT.match(value))}

    def _gap(self, height):
        if 'gap' not in self.macros or not self.spaces:
            return None
        name = _nearest(height, self.spaces)
        return 'gap::' if name == 'm' else f'gap::{name}'

    def _declarations(self, style, line, macro=None, layout=None):
        """Findings for one style group 'a:b; c:d' (of the macro `macro`, in a
        page of layout `layout`)."""
        found = []
        declarations = {}
        for part in style.split(';'):
            if ':' in part:
                key, value = part.split(':', 1)
                declarations[key.strip().lower()] = value.strip()
        position = declarations.get('position', '').lower()
        if position in ('fixed', 'absolute'):
            placed = '; '.join(f'{k}:{declarations[k]}' for k in ('position', 'top', 'left', 'right', 'bottom')
                               if k in declarations)
            advice = []
            if self.layouts & {'side', 'stack'}:
                advice.append("a layout ({% set layout = 'side' %} or 'stack', the figures in media::)")
            if 'aside' in self.macros:
                advice.append('aside:: for a figure beside the text')
            found.append(Finding(line, 'position', placed, ' or '.join(advice) or 'the flow of the page'))
        elif macro not in OFFSET_MACROS:
            offsets = [f'{k}:{declarations[k]}' for k in ('margin-top', 'margin-left', 'top', 'left')
                       if (m := PX.match(declarations.get(k, ''))) and float(m.group(1)) >= 20]
            if offsets:
                advice = [a for a, present in (('gap:: (vertical space)', 'gap' in self.macros),
                                               ('a layout', bool(self.layouts)),
                                               ('cols:: / col::', 'cols' in self.macros)) if present]
                found.append(Finding(line, 'offset', '; '.join(offsets),
                                     ' or '.join(advice) or 'the flow of the page'))
        size = declarations.get('font-size')
        if size and (m := PERCENT.match(size)) and float(m.group(1)) != 100 and self.fonts:
            name = _nearest(float(m.group(1)), self.fonts)
            found.append(Finding(line, 'font-size', f'font-size:{size}',
                                 f'{name}:: ({self.fonts[name]:g} %)'))
        if 'line-height' in declarations and not size:
            advice = [f'{n}:: (tight lines)' for n in ('small', 'tiny') if n in self.macros]
            found.append(Finding(line, 'line-height', f"line-height:{declarations['line-height']}",
                                 ' or '.join(advice + ['the line height of the theme'])))
        if declarations.get('display', '').lower() == 'none':
            found.append(Finding(line, 'display', 'display:none', '(.hidden)'))
        sizes = [f'{k}:{declarations[k]}' for k in ('width', 'height') if k in declarations]
        if sizes and layout in ('side', 'stack') and macro in ('img', 'video', 'videoplay'):
            found.append(Finding(line, 'size', '; '.join(sizes),
                                 'media:: fits the figures (media::(.fill) enlarges them)'))
        display = declarations.get('display', '').lower()
        if (display in ('flex', 'inline-block') or 'justify-content' in declarations) and 'cols' in self.macros:
            found.append(Finding(line, 'flex', f'display:{display}' if display else 'justify-content',
                                 'cols:: with col:: children'))
        if declarations.get('text-align', '').lower() == 'center' and 'center' in self.macros:
            found.append(Finding(line, 'align', 'text-align:center', 'center::'))
        if declarations.get('color', '').lower() in ('gray', 'grey') and 'muted' in self.macros:
            found.append(Finding(line, 'color', f"color:{declarations['color']}",
                                 'muted:: (or credit:: for a caption)'))
        return found

    def lint_file(self, path, layout=None):
        with open(path, encoding='utf-8', errors='replace') as fid:
            return self.lint(fid.read(), layout)

    def lint(self, source, layout=None):
        """Findings of the source of a page (a text or a source_scan.Scan);
        `layout`: the layout given by its configuration or deck entry (a
        {% set layout %} of the page takes precedence). Code and verbatim
        blocks, math, comments and inline code are not read (lib/source_scan.py)."""
        findings = []
        source = source_scan.scan(source)
        read = source.masked
        set_layout = source_scan.layout_setting(source)
        if set_layout:
            layout, layout_line, offset = set_layout
            if not _layout_applies(source, offset):
                findings.append(Finding(layout_line, 'layout', f"{{% set layout = '{layout}' %}} not at the top",
                                        'move it to the top of the page: only blank lines, comments, '
                                        '{% set %} and {% import %} may come before it (else it is ignored)'))
        else:
            layout_line = 1
        base = self._layout_base(layout)
        for number, line in enumerate(read.split('\n'), 1):
            stripped = line.strip()
            if (m := SPACER.match(line)):
                height = float(m.group(1))
                gap = self._gap(height)
                findings.append(Finding(number, 'spacer', stripped, gap or 'a margin of the design'))
                continue
            for m in STYLE.finditer(line):
                macro = m.group(1).split('::')[0] if m.group(1) else None
                findings += self._declarations(m.group(2) or m.group(3), number, macro, base)
            if RAW_IFRAME.search(line) and 'demo' in self.macros:
                findings.append(Finding(number, 'iframe', '<iframe style=...>',
                                        'demo::url (size: the tokens of the design, or media::)'))
        if layout:
            if base is None:
                findings.append(Finding(layout_line, 'layout', f'layout {layout}',
                                        f"a layout of the design: {', '.join(sorted(self.layouts)) or 'none'}"))
            elif base in ('side', 'stack') and 'media::' not in read:
                findings.append(Finding(layout_line, 'layout', f'layout {layout} without media::',
                                        'put the figures in media:: ... ::'))
            elif base == 'side' and re.search(r'(?<![\w-])aside::', read):
                findings.append(Finding(layout_line, 'layout', 'aside:: in layout side', 'media::'))
        return findings

    def _layout_base(self, layout):
        """The layout of the design named by `layout`, or None: its name, or
        the part before its first - (side-s: side), as the theme reads it."""
        if not layout:
            return None
        layout = str(layout)
        if layout in self.layouts:
            return layout
        base = layout.split('-', 1)[0]
        return base if base in self.layouts else None
