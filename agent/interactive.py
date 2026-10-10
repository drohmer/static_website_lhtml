"""Bounded declarative interactive verification scenarios."""
from fnmatch import fnmatchcase
import re


def validate(spec):
    if not isinstance(spec, dict) or set(spec) - {'enabled', 'auto_media', 'max_states', 'pages'}:
        raise ValueError('layout_report.interactive: expected enabled, auto_media, max_states, pages')
    for key in ('enabled', 'auto_media'):
        if key in spec and not isinstance(spec[key], bool):
            raise ValueError(f'layout_report.interactive.{key} must be boolean')
    limit = spec.get('max_states', 8)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 16:
        raise ValueError('layout_report.interactive.max_states must be an integer from 1 to 16')
    pages = spec.get('pages', {})
    if not isinstance(pages, dict):
        raise ValueError('layout_report.interactive.pages must be a mapping')
    for pattern, states in pages.items():
        if not isinstance(pattern, str) or not isinstance(states, list) or len(states) > 16:
            raise ValueError('layout_report.interactive: invalid page pattern or state list')
        names = set()
        for state in states:
            if not isinstance(state, dict) or set(state) - {'name', 'time_ms', 'actions', 'expect'}:
                raise ValueError('layout_report.interactive: invalid state fields')
            name = state.get('name', '')
            if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,63}', name) \
                    or name in names or name.startswith('auto-'):
                raise ValueError('layout_report.interactive: names must be unique safe identifiers; auto- is reserved')
            names.add(name)
            time = state.get('time_ms', 0)
            if isinstance(time, bool) or not isinstance(time, (int, float)) or not 0 <= time <= 5000:
                raise ValueError('layout_report.interactive.time_ms must be between 0 and 5000')
            for key in ('actions', 'expect'):
                values = state.get(key, [])
                if not isinstance(values, list) or len(values) > 16:
                    raise ValueError(f'layout_report.interactive.{key}: at most 16 entries')
                for item in values:
                    allowed = {'frame', 'selector', 'visible'} if key == 'expect' else {'frame', 'selector', 'type', 'value', 'key'}
                    if not isinstance(item, dict) or set(item) - allowed:
                        raise ValueError(f'layout_report.interactive: invalid {key} fields')
                    if not isinstance(item.get('selector'), str) or not item['selector'].strip():
                        raise ValueError('layout_report.interactive: selector is required')
                    if 'frame' in item and (not isinstance(item['frame'], str) or not item['frame'].strip()):
                        raise ValueError('layout_report.interactive: frame must be a selector')
                    if key == 'expect':
                        if not isinstance(item.get('visible', True), bool):
                            raise ValueError('layout_report.interactive: visible must be boolean')
                    else:
                        kind = item.get('type')
                        if kind not in ('click', 'input', 'key'):
                            raise ValueError('layout_report.interactive: action must be click, input or key')
                        required = 'value' if kind == 'input' else 'key' if kind == 'key' else None
                        if required and not isinstance(item.get(required), str):
                            raise ValueError(f'layout_report.interactive: {required} must be a string')
                        if (kind != 'input' and 'value' in item) or (kind != 'key' and 'key' in item):
                            raise ValueError('layout_report.interactive: field does not match action type')
    return spec


def options_for(spec, page, default_enabled=False):
    validate(spec)
    plans = [state for pattern, states in spec.get('pages', {}).items()
             if fnmatchcase(page, pattern) for state in states]
    if len({state['name'] for state in plans}) != len(plans):
        raise ValueError(f'layout_report.interactive: duplicate state names for {page}')
    return {'enabled': spec.get('enabled', default_enabled), 'auto_media': spec.get('auto_media', True),
            'max_states': spec.get('max_states', 8), 'plans': plans}
