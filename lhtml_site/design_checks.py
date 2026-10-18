"""Role-aware design warnings: configurable evidence, not aesthetic approval."""
from copy import deepcopy
from statistics import median
import math

from lhtml_site.layout.geometry import ancestors, nearest_ancestor, rect

ROLES = ('title', 'heading', 'body', 'caption', 'reference', 'code', 'formula', 'figure', 'decorative')
DEFAULTS = {
    'title': {'min_font': 32, 'min_body_ratio': 1.25, 'max_lines': 2},
    'heading': {'min_font': 24, 'min_body_ratio': 1.05},
    'body': {'min_font': 20}, 'caption': {'min_font': 12, 'max_body_ratio': 1.05, 'max_figure_gap': 64},
    'reference': {'min_font': 10}, 'code': {'min_font': 18},
    'formula': {'min_font': 20}, 'figure': {'min_extent': 32}, 'decorative': {},
}
FIELDS = {role: set(values) for role, values in DEFAULTS.items()}


def validate(spec):
    """Fail early on typos; None disables one check and enabled:false disables all."""
    if not isinstance(spec, dict) or set(spec) - {'enabled', 'roles', 'layouts'}:
        raise ValueError('layout.design_rules: expected enabled, roles and layouts mappings')
    if 'enabled' in spec and not isinstance(spec['enabled'], bool):
        raise ValueError('layout.design_rules.enabled must be boolean')
    def roles(values):
        if not isinstance(values, dict) or set(values) - set(ROLES):
            raise ValueError('layout.design_rules: unknown role or invalid roles mapping')
        for role, rules in values.items():
            if not isinstance(rules, dict) or set(rules) - FIELDS[role]:
                raise ValueError(f'layout.design_rules: invalid checks for {role}')
            for key, value in rules.items():
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                          or not math.isfinite(value) or value <= 0):
                    raise ValueError(f'layout.design_rules: {role}.{key} must be positive or null')
    roles(spec.get('roles', {}))
    layouts = spec.get('layouts', {})
    if not isinstance(layouts, dict):
        raise ValueError('layout.design_rules.layouts must be a mapping')
    for name, values in layouts.items():
        if not isinstance(name, str):
            raise ValueError('layout.design_rules: layout names must be strings')
        roles(values)
    return spec


def rules_for(layout, spec):
    validate(spec)
    rules = deepcopy(DEFAULTS)
    for overrides in [spec.get('roles', {}), spec.get('layouts', {}).get(layout.get('layout_name'), {})]:
        for role, values in overrides.items():
            rules[role].update(values)
    return rules


def analyse_design(layout, spec=None):
    spec = spec or {}
    rules = rules_for(layout, spec)
    nodes = layout.get('subblocks', []) + [b for b in layout.get('blocks', []) if b.get('design_role')]
    # Thresholds are CSS pixels at a 1920px-wide render, scaled to the viewport.
    scale = (layout.get('viewport') or {}).get('w', 1920) / 1920
    def text(b):
        return b.get('design_text', b.get('text')) or {}
    body = [b['font_size'] for b in nodes if b.get('design_role') == 'body'
            and text(b).get('words') and b.get('font_size')]
    baseline = median(body) if body else None
    info = {'enabled': spec.get('enabled', True), 'layout': layout.get('layout_name'),
            'rules': rules, 'pixel_scale': scale, 'body_font': baseline,
            'measured': bool(layout.get('design_measurement'))}
    result = []
    if not info['enabled'] or not nodes:
        return result, info
    def finding(b, check, value, limit, advice, **extra):
        result.append({'id': b['id'], 'kind': check, 'role': b['design_role'],
                       'value': round(value, 2), 'limit': round(limit, 2), 'advice': advice, **extra})
    by_id = {b['id']: b for b in nodes}
    for b in nodes:
        role = b.get('design_role')
        if role not in rules or not b.get('ink'):
            continue
        policy = rules[role]
        prose = text(b).get('words', 0)
        font = text(b).get('min_font') or b.get('font_size')
        if policy.get('min_font') and font and (prose or role in ('formula', 'code')):
            limit = policy['min_font'] * scale
            if font < limit - .5:
                finding(b, 'font_min', font, limit, f'Increase the {role} font or shorten its content.')
        if baseline and prose and font:
            if policy.get('min_body_ratio') and b['font_size'] < baseline * policy['min_body_ratio'] - .5:
                finding(b, 'title_hierarchy', b['font_size'] / baseline, policy['min_body_ratio'],
                        'Increase the title/heading size relative to body text.')
            if policy.get('max_body_ratio') and b['font_size'] > baseline * policy['max_body_ratio'] + .5:
                finding(b, 'caption_hierarchy', b['font_size'] / baseline, policy['max_body_ratio'],
                        'Keep the caption subordinate to the body text.')
        if policy.get('max_lines') and b.get('design_lines', 0) > policy['max_lines']:
            finding(b, 'title_lines', b['design_lines'], policy['max_lines'], 'Shorten the title or adjust its width.')
        if role == 'figure' and policy.get('min_extent'):
            # Use rendered media boxes, not the sparse ink of a diagram or logo.
            box = b.get('box') or {}
            extent = min(box.get('w', 0), box.get('h', 0))
            if 0 < extent < policy['min_extent'] * scale:
                finding(b, 'figure_size', extent, policy['min_extent'] * scale,
                        'Enlarge the figure; use data-lhtml-role="decorative" for an ornament.')
        if role == 'caption' and policy.get('max_figure_gap'):
            # Pair only within an explicit figure/media container or a column.
            parent = nearest_ancestor(b, by_id, lambda n: n.get('figure_container') or n.get('role') == 'column')
            if not parent:
                continue
            candidates = [n for n in nodes if n.get('design_role') == 'figure'
                          and any(a['id'] == parent['id'] for a in ancestors(n, by_id))]
            c = b.get('visual') or b['box']
            cx0, _, cx1, _ = rect(c)
            distances = []
            for n in candidates:
                r = n['box']
                rx0, _, rx1, _ = rect(r)
                if min(cx1, rx1) <= max(cx0, rx0):        # not above or below one another
                    continue
                gap = max(0, c['y'] - r['y'] - r['h'], r['y'] - c['y'] - c['h'])
                distances.append((gap, n['id']))
            if distances:
                gap, figure = min(distances)
                if gap > policy['max_figure_gap'] * scale:
                    finding(b, 'caption_gap', gap, policy['max_figure_gap'] * scale,
                            'Move the caption nearer its figure.', by=figure)
    return result, info
