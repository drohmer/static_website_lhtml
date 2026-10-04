"""Design of a site or deck: tokens (sizes, colors, spacing) and LHTML macros.

The theme provides defaults in `<theme>/design.yaml`; the `design` key of the
configuration (a mapping, or the path of a YAML file) overrides them, key by
key. Example:

    tokens:
      font:  {small: 85%}            # -> CSS variable --font-small
      space: {m: 25px}               # -> --space-m
    macros:
      small: {class: small, css: '.small { font-size: var(--font-small); }',
              doc: 'Smaller text. small:: text ::'}

The generator writes `theme/css/design.css` (the tokens as CSS variables on
:root, then the `css` of each macro) and passes the macros to LHTML.
"""
from __future__ import annotations

from pathlib import Path
import copy
import re

import yaml

DESIGN_FILE = 'design.yaml'
CSS_PATH = 'theme/css/design.css'
SECTIONS = ('tokens', 'macros')
TOKEN_NAME = re.compile(r'[A-Za-z0-9_-]+$')


class DesignError(ValueError):
    """Invalid design file or design configuration."""


def _read_yaml(path):
    try:
        with open(path, encoding='utf-8') as stream:
            data = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise DesignError(f"Cannot read design file '{path}': {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise DesignError(f"Design file '{path}' must contain a mapping")
    return data


def merge(base, override):
    """Recursive merge of mappings: values of `override` replace those of `base`;
    a value None removes the key (e.g. to disable a macro of the theme)."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _check(design, origin):
    unknown = set(design) - set(SECTIONS)
    if unknown:
        raise DesignError(f"{origin}: unknown design section(s) {', '.join(sorted(unknown))} "
                          f"(expected {', '.join(SECTIONS)})")
    for section in SECTIONS:
        if not isinstance(design.get(section, {}), dict):
            raise DesignError(f"{origin}: '{section}' must be a mapping")
    return design


def load_design(theme_directory, override=None):
    """Design of the theme merged with `override` (a mapping, a YAML file path, or None)."""
    design = {}
    theme_file = Path(theme_directory) / DESIGN_FILE
    if theme_file.is_file():
        design = _check(_read_yaml(theme_file), str(theme_file))
    if isinstance(override, (str, Path)):
        override = _check(_read_yaml(override), str(override))
    elif override:
        override = _check(dict(override), "'design' of the configuration")
    if override:
        design = merge(design, override)
    return {section: design.get(section) or {} for section in SECTIONS}


def flatten_tokens(tokens, prefix=''):
    """{'font': {'small': '85%'}} -> {'font-small': '85%'}"""
    flat = {}
    for key, value in tokens.items():
        name = f'{prefix}-{key}' if prefix else str(key)
        if not TOKEN_NAME.match(str(key)):
            raise DesignError(f"Invalid token name '{name}' (letters, digits, - and _ only)")
        if isinstance(value, dict):
            flat.update(flatten_tokens(value, name))
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            flat[name] = str(value)
        else:
            raise DesignError(f"Token '{name}' must be a value or a mapping, got {value!r}")
    return flat


def design_css(design):
    lines = ['/* Generated from design.yaml: edit the design, not this file. */', '', ':root {']
    lines += [f'    --{name}: {value};' for name, value in flatten_tokens(design['tokens']).items()]
    lines.append('}')
    for name, spec in design['macros'].items():
        css = (spec or {}).get('css')
        if css:
            lines += ['', f'/* {name}:: */', str(css).strip()]
    return '\n'.join(lines) + '\n'


def lhtml_macros(design):
    """Macro definitions for LHTML (without the fields used only here)."""
    return {name: {k: v for k, v in (spec or {}).items() if k not in ('css', 'doc')}
            for name, spec in design['macros'].items()}


def _resolve(value, tokens, depth=0):
    """var(--x) -> value of the token x (for the reference documentation)."""
    if depth > 5:
        return value
    return re.sub(r'var\(--([A-Za-z0-9_-]+)\)',
                  lambda m: _resolve(tokens[m.group(1)], tokens, depth + 1) if m.group(1) in tokens
                  else m.group(0), value)


def design_markdown(design):
    """Reference of the macros and tokens, for authors and LLMs."""
    tokens = flatten_tokens(design['tokens'])
    out = ['# Design reference', '',
           'Generated from `design.yaml` (theme) and the `design` key of the configuration.',
           'Use these macros instead of inline styles; write `[...]` only for a real exception',
           '(e.g. `aside::[top:400px;]`). The classes, style and attributes written in the',
           'source are added to those of the macro. A macro is closed by `::` or `::name[-]`.', '',
           '## Macros', '']
    for name, spec in design['macros'].items():
        spec = spec or {}
        out.append(f'### `{name}::`')
        out.append('')
        if spec.get('doc'):
            out += [str(spec['doc']).strip(), '']
        html = f"<{spec.get('tag', 'div')} class=\"{spec.get('class', '')}\">"
        details = [f'HTML: `{html}`']
        if spec.get('variant'):
            values = spec['variant'] if isinstance(spec['variant'], list) else ['<any>']
            details.append(f"variants: {', '.join(f'`{name}::{v}`' for v in values)}"
                           + (f" (default `{spec['default']}`)" if spec.get('default') else ''))
        if spec.get('empty'):
            details.append('no content (closed at once)')
        if spec.get('url'):
            details.append(f"`{name}::url` sets `{spec['url']}`")
        out += [f'- {d}' for d in details]
        if spec.get('css'):
            out += ['', '```css', _resolve(str(spec['css']).strip(), tokens), '```']
        out.append('')
    out += ['## Tokens', '', 'CSS variables (`var(--name)`), in `theme/css/design.css`.', '',
            '| token | value |', '|---|---|']
    out += [f'| `--{name}` | `{value}` |' for name, value in tokens.items()]
    return '\n'.join(out) + '\n'


def write_design(meta, design):
    """Write theme/css/design.css in the site directory."""
    path = Path(meta['site_directory']) / CSS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(design_css(design), encoding='utf-8')
    return path
