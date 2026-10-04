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

A design file may start from another one: `extends: ../slides/design.yaml`
(relative to the file), then override it key by key.

The generator writes `theme/css/design.css` (the tokens as CSS variables on
:root, then the `css` of each macro) and `structure/design.md` (reference of
the macros and tokens, for authors and LLMs), and passes the macros to LHTML
(which ignores their `css` and `doc` fields).
"""
from __future__ import annotations

from pathlib import Path
import copy
import re

import yaml

DESIGN_FILE = 'design.yaml'
CSS_PATH = 'theme/css/design.css'
REFERENCE_PATH = 'structure/design.md'
SECTIONS = ('tokens', 'macros')
MAX_EXTENDS = 10
TOKEN_NAME = re.compile(r'[A-Za-z0-9_-]+$')


class DesignError(ValueError):
    """Invalid design file or design configuration (the message starts with 'Design: ')."""

    def __init__(self, message):
        super().__init__(f'Design: {message}')


def _read_yaml(path):
    try:
        with open(path, encoding='utf-8') as stream:
            data = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise DesignError(f"cannot read '{path}': {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise DesignError(f"'{path}' must contain a mapping")
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
    unknown = set(design) - set(SECTIONS) - {'extends'}
    if unknown:
        raise DesignError(f"{origin}: unknown design section(s) {', '.join(sorted(unknown))} "
                          f"(expected {', '.join(SECTIONS)})")
    for section in SECTIONS:
        if not isinstance(design.get(section) or {}, dict):
            raise DesignError(f"{origin}: '{section}' must be a mapping")
    for name, spec in (design.get('macros') or {}).items():
        if spec is not None and not isinstance(spec, dict):
            raise DesignError(f"{origin}: macro '{name}' must be a mapping (or null to remove it), "
                              f"got {spec!r}")
    return design


def _load(source, base, origin, depth=0):
    """A design given as a YAML file path or a mapping, with what it extends."""
    if depth > MAX_EXTENDS:
        raise DesignError(f"{origin}: too many 'extends' (loop?)")
    if isinstance(source, (str, Path)):
        origin = str(source)
        base = Path(source).parent
        source = _read_yaml(source)
    design = _check(dict(source), origin)
    parent = design.pop('extends', None)
    if parent is None:
        return design
    if not isinstance(parent, str):
        raise DesignError(f"{origin}: 'extends' must be the path of a design file")
    path = Path(parent).expanduser()
    if not path.is_absolute():
        path = Path(base) / path
    return merge(_load(path, path.parent, str(path), depth + 1), design)


def load_design(theme_directory, override=None, base_directory='.'):
    """Design of the theme merged with `override` (a mapping, a YAML file path,
    or None); relative paths of a mapping are resolved from `base_directory`."""
    design = {}
    theme_file = Path(theme_directory) / DESIGN_FILE
    if theme_file.is_file():
        design = _load(theme_file, theme_directory, str(theme_file))
    if override:
        design = merge(design, _load(override, base_directory, "'design' of the configuration"))
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
    """Write theme/css/design.css and structure/design.md in the site directory."""
    site = Path(meta['site_directory'])
    for relative, text in ((CSS_PATH, design_css(design)), (REFERENCE_PATH, design_markdown(design))):
        (site / relative).parent.mkdir(parents=True, exist_ok=True)
        (site / relative).write_text(text, encoding='utf-8')
    return site / CSS_PATH
