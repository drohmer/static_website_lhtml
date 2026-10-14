"""Structured verification reports. Geometry is evidence, not an aesthetic verdict."""
import hashlib
import json
from pathlib import Path

ERROR_KEYS = ('collisions', 'hidden_text', 'out_of_area', 'clipped', 'upscaled_images',
              'reserved', 'collapsed', 'svg_overflow', 'internal_collisions', 'internal_overflow', 'internal_clipped', 'interactive_errors')
WARNING_KEYS = ('tight', 'near_aligned', 'dense', 'wrapped', 'short_wrapped', 'rows', 'fit', 'svg_labels', 'deviations', 'lint', 'internal_tight', 'role_design', 'canvas_overlaps')


def diagnostics(layout):
    blocks = {b['id']: b for b in layout.get('blocks', []) + layout.get('subblocks', [])}
    result, occurrences = [], {}
    for severity, keys in (('error', ERROR_KEYS), ('warning', WARNING_KEYS)):
        for kind in keys:
            for finding in layout.get('analysis', {}).get(kind, []):
                ids = list(dict.fromkeys(finding[k] for k in ('id', 'a', 'b', 'by', 'parent')
                                        if k in finding and finding[k] in blocks))
                affected = [blocks[i] for i in ids]
                # Source location anchors survive style and text changes, but not inserted lines.
                anchors = [b.get('stable_id') or b.get('source') or f"{layout.get('source')}:{b.get('line')}:{b.get('kind')}"
                           for b in affected]
                key = kind + ':' + hashlib.sha256(json.dumps([anchors, finding.get('src'), finding.get('kind'), finding.get('source_anchor') or finding.get('line')],
                                                            sort_keys=True).encode()).hexdigest()[:16]
                occurrences[key] = occurrences.get(key, 0) + 1
                identity = f'{key}:{occurrences[key]}'
                sources = [r for b in affected for r in (b.get('provenance') or {}).get('ranges', [])]
                if not sources:
                    sources = [{'file': b['source'].rsplit(':', 1)[0] if b.get('source') else layout.get('source'),
                                'line': b.get('line')} for b in affected]
                if not sources and finding.get('line'):
                    sources = [{'file': layout.get('source'), 'line': finding['line']}]
                if kind == 'interactive_errors' and not sources:
                    sources = [{'file': layout.get('source'), 'line': None}]
                rects = [b.get('visual') or b.get('box') for b in affected]
                rects = [r for r in rects if r]
                bounds = None
                if all(k in finding for k in ('x0', 'y0', 'x1', 'y1')):
                    bounds = {k: finding[k] for k in ('x0', 'y0', 'x1', 'y1')}
                elif rects:
                    bounds = {'x0': min(r['x'] for r in rects), 'y0': min(r['y'] for r in rects),
                              'x1': max(r['x'] + r['w'] for r in rects),
                              'y1': max(r['y'] + r['h'] for r in rects)}
                result.append({'id': identity, 'type': kind, 'severity': severity,
                               'method': 'unverified_raster_overlap' if kind == 'canvas_overlaps' else 'interaction_execution' if kind == 'interactive_errors' else 'source_lint' if kind == 'lint' else 'role_design_rule' if kind == 'role_design' else 'deterministic_geometry',
                               'blocks': ids, 'block_anchors': anchors, 'sources': sources,
                               'source_precision': [b.get('source_precision', 'aggregate') for b in affected],
                               'media_provenance': [m['provenance'] for b in affected for m in b.get('media', []) if m.get('provenance')],
                               'evidence': dict(finding), 'bounds': bounds})
    for frame in layout.get('frame_layouts', []):
        for item in diagnostics(frame['layout']):
            item['id'] = 'frame:' + frame['id'] + ':' + item['id']
            item['frame_id'] = frame['id']
            bounds, box = item.get('bounds'), frame.get('box')
            viewport = frame['layout'].get('viewport', {})
            if bounds and box and viewport.get('w') and viewport.get('h'):
                sx, sy = box['width'] / viewport['w'], box['height'] / viewport['h']
                item['bounds'] = {k: box['x' if k.startswith('x') else 'y'] + value * (sx if k.startswith('x') else sy)
                                  for k, value in bounds.items()}
            result.append(item)
    for state in layout.get('interactive', {}).get('states', []):
        if 'layout' not in state:
            continue
        for item in diagnostics(state['layout']):
            item['id'] = 'state:' + state['id'] + ':' + item['id']
            item['state_id'] = state['id']
            result.append(item)
    return result


def report(layout, previous=None):
    items = diagnostics(layout)
    health = layout.get('render_health', {'status': 'unknown', 'errors': [], 'unchecked': []})
    validity = layout.get('freshness')
    status = ('failed' if health['status'] == 'failed' else
              'incomplete' if validity and validity['status'] != 'current' else
              'incomplete' if health['status'] != 'ready' or health.get('unchecked') or layout.get('internal_measurement', {}).get('truncated') else
              'issues' if items else 'pass')
    interactive = layout.get('interactive', {})
    states = interactive.get('states', [])
    children = [f['layout'] for f in layout.get('frame_layouts', [])] + [s['layout'] for s in states if 'layout' in s]
    statuses = {status} | {report(child)['status'] for child in children}
    if any(s['status'] == 'failed' for s in states):
        statuses.add('failed')
    if interactive.get('truncated'):
        statuses.add('incomplete')
    status = next((s for s in ('failed', 'incomplete', 'issues') if s in statuses), 'pass')
    old = diagnostics(previous) if previous else []
    before, after = {d['id']: d for d in old}, {d['id']: d for d in items}
    return {'schema_version': 1, 'status': status, 'source': layout.get('source'),
            'page_context': layout.get('page_context', {}),
            'freshness': validity or {'status': 'unknown'},
            'verification_mode': layout.get('verification_mode', False),
            'dependencies': layout.get('dependencies'), 'internal_measurement': layout.get('internal_measurement'),
            'design_checks': layout.get('design_checks'),
            'interactive_coverage': {k: v for k, v in interactive.items() if k != 'states'} | {
                'measured': sum('layout' in s for s in states),
                'failed': [s['id'] for s in states if s['status'] == 'failed']},
            'states': [{'id': s['id'], 'status': report(s['layout'])['status'] if 'layout' in s else 'failed',
                        'report': 'states/' + s['id'] + '/verification.json'} for s in states],
            'frames': [{'id': f['id'], 'status': report(f['layout'])['status'],
                        'report': 'frames/' + f['id'] + '/verification.json'} for f in layout.get('frame_layouts', [])],
            'render_health': health, 'checks': {'geometry': True, 'render_health': True,
                'internal_geometry': bool(layout.get('internal_measurement')),
                'role_design': bool(layout.get('design_measurement')) and layout.get('design_checks', {}).get('enabled', False),
                'visual_review': False, 'interactive_states': bool(states) and not interactive.get('truncated')
                    and all('layout' in s for s in states)},
            'identity_method': 'persistent_source_anchor_or_explicit_dom_id; ambiguous_edits_receive_new_ids',
            'diagnostics': items, 'artifacts': {'render': 'render.png', 'layout': 'layout.json'},
            'changes': {'baseline_available': previous is not None,
                'introduced': [d for k, d in after.items() if k not in before],
                'resolved': [d for k, d in before.items() if k not in after],
                'persisting': sorted(before.keys() & after.keys()),
                'updated': [{'before': before[k], 'after': d} for k, d in after.items()
                            if k in before and d != before[k]]}}


def write_report(folder, layout, previous=None):
    folder = Path(folder)
    value = report(layout, previous)
    (folder / 'verification.json').write_text(json.dumps(value, indent=2, ensure_ascii=False))
    (folder / 'changes.json').write_text(json.dumps(value['changes'], indent=2, ensure_ascii=False))
    return value


def refresh_report(folder, layout):
    """Update validity of a retained measurement without inventing a new baseline."""
    folder = Path(folder)
    value = report(layout)
    try:
        previous = json.loads((folder / 'verification.json').read_text())
    except (OSError, ValueError):
        previous = {}
    previous_items = {d['id']: d for d in previous.get('diagnostics', [])}
    for diagnostic in value['diagnostics']:
        crop = previous_items.get(diagnostic['id'], {}).get('evidence', {}).get('crop')
        if crop and (folder / crop).is_file():
            diagnostic['evidence']['crop'] = crop
    for key in ('changes', 'artifacts'):
        if key in previous:
            value[key] = previous[key]
    (folder / 'verification.json').write_text(json.dumps(value, indent=2, ensure_ascii=False))
    return value
