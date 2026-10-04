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

STYLE = re.compile(r'\[([^\[\]\n]*:[^\[\]\n]*)\]|style="([^"]*)"')
SPACER = re.compile(r'^\s*(?:div)?::\[\s*height:\s*([\d.]+)px;?\s*\]::?\s*$')
LAYOUT_SET = re.compile(r'''\{%-?\s*set\s+layout\s*=\s*['"]([^'"]*)['"]\s*-?%\}''')
CODE_START = re.compile(r'^\s*(?:code|verbatim)::')
MACRO = re.compile(r'(?<![\w-])([A-Za-z][\w-]*)::')
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


class Linter:
    """Lint of the pages for a design (design.load_design)."""

    def __init__(self, design):
        self.macros = set(design.get('macros') or {})
        self.layouts = set(design.get('layouts') or {})
        tokens = design.get('tokens') or {}
        self.spaces = _px_tokens(tokens.get('space'))
        self.fonts = {name: float(m.group(1)) for name, value in (tokens.get('font') or {}).items()
                      if name in self.macros and isinstance(value, str) and (m := PERCENT.match(value))}

    def _gap(self, height):
        if 'gap' not in self.macros or not self.spaces:
            return None
        name = _nearest(height, self.spaces)
        return 'gap::' if name == 'm' else f'gap::{name}'

    def _declarations(self, style, line):
        """Findings for one style group 'a:b; c:d'."""
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
        else:
            offsets = [f'{k}:{declarations[k]}' for k in ('margin-top', 'margin-left', 'top', 'left')
                       if (m := PX.match(declarations.get(k, ''))) and float(m.group(1)) >= 20]
            if offsets:
                advice = [a for a, present in (('gap:: (vertical space)', 'gap' in self.macros),
                                               ('a layout', bool(self.layouts)),
                                               ('cols:: / col::', 'cols' in self.macros)) if present]
                found.append(Finding(line, 'offset', '; '.join(offsets),
                                     ' or '.join(advice) or 'the flow of the page'))
        size = declarations.get('font-size')
        if size and (m := PERCENT.match(size)) and float(m.group(1)) < 100 and self.fonts:
            name = _nearest(float(m.group(1)), self.fonts)
            found.append(Finding(line, 'font-size', f'font-size:{size}',
                                 f'{name}:: ({self.fonts[name]:g} %)'))
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

    def lint(self, text, layout=None):
        """Findings of the source `text` of a page; `layout`: the layout given
        by its configuration or deck entry (a {% set layout %} of the page
        takes precedence)."""
        findings = []
        in_code = False
        lines = text.split('\n')
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if in_code:
                in_code = stripped != '::'
                continue
            if CODE_START.match(line):
                in_code = not line.split('::', 1)[1].rstrip().endswith('::')    # else inline code
                continue
            if (m := SPACER.match(line)):
                height = float(m.group(1))
                gap = self._gap(height)
                findings.append(Finding(number, 'spacer', stripped, gap or 'a margin of the design'))
                continue
            for m in STYLE.finditer(line):
                findings += self._declarations(m.group(1) or m.group(2), number)
        set_layout = LAYOUT_SET.search(text)
        layout = set_layout.group(1) if set_layout else layout
        if layout:
            line = text[:set_layout.start()].count('\n') + 1 if set_layout else 1
            base = str(layout).split('-')[0]
            if base not in self.layouts:
                findings.append(Finding(line, 'layout', f'layout {layout}',
                                        f"a layout of the design: {', '.join(sorted(self.layouts)) or 'none'}"))
            elif base in ('side', 'stack') and 'media::' not in text:
                findings.append(Finding(line, 'layout', f'layout {layout} without media::',
                                        'put the figures in media:: ... ::'))
            elif base == 'side' and re.search(r'(?<![\w-])aside::', text):
                findings.append(Finding(line, 'layout', 'aside:: in layout side', 'media::'))
        return findings


def report(findings_by_page):
    """Text report: {label: (path, findings)} -> lines 'path:line: kind: text -> advice'."""
    lines = []
    for label, (path, findings) in findings_by_page.items():
        for f in findings:
            lines.append(f'{path}:{f.line}: {f.kind}: {f.text}\n    -> {f.advice}')
    return lines
