"""Source-centred work queue; occurrences retain their rendered evidence."""
import hashlib
import json
from pathlib import Path

ADVICE = {
    'collisions': 'Adjust spacing or layout of the affected blocks; inspect their ink overlay.',
    'internal_collisions': 'Adjust the containing column or block spacing; inspect internal-overlay.png.',
    'internal_overflow': 'Increase the column width or use a better fitting formula/layout macro.',
    'out_of_area': 'Fit the content within the slide using the project layout and size tokens.',
    'clipped': 'Remove unintended clipping or fit content in its container.',
    'internal_clipped': 'Fit the child content in its container; check the clipping ancestor.',
    'hidden_text': 'Reposition the covering block or the text; verify the rendered crop.',
    'interactive_errors': 'Repair the scenario selector, assertion or runtime failure before design edits.',
    'canvas_overlaps': 'Inspect the canvas screenshot: rectangular bounds do not establish painted overlap.',
}


def group_key(item):
    # State/frame IDs are capture-local. Source documents distinguish embedded apps.
    sources = sorted({s.get('file') or '' for s in item.get('sources', [])})
    anchors = sorted(item.get('block_anchors', []))
    if not anchors and item.get('evidence', {}).get('source_anchor'):
        anchors = [item['evidence']['source_anchor']]
    if not anchors:
        anchors = sorted(json.dumps(s, sort_keys=True) for s in item.get('sources', []))
    evidence = item.get('evidence', {})
    identity = [item['type'], item.get('method'), sources, anchors,
                evidence.get('check'), evidence.get('kind'), evidence.get('role')]
    return 'issue-' + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]


def classify(item):
    if item.get('method') == 'interaction_execution':
        return 'execution_failure', 0
    if item.get('method') == 'unverified_raster_overlap':
        return 'visual_candidate', 3
    if item.get('severity') == 'error' and item.get('method') == 'deterministic_geometry':
        return 'measured_defect', 1
    return 'review_rule', 2


def queue(reports):
    groups = {}
    for page, report_path, value in reports:
        for item in value.get('diagnostics', []):
            key = group_key(item)
            category, priority = classify(item)
            group = groups.setdefault(key, {'id': key, 'type': item['type'], 'category': category,
                'priority': priority, 'sources': [], 'occurrences': [], 'proposal': {
                    'action': item.get('evidence', {}).get('advice') or item.get('evidence', {}).get('suggestion') or ADVICE.get(item['type'], 'Inspect the source and rendered evidence before choosing a layout correction.'),
                    'requires_visual_review': category != 'execution_failure'}})
            for source in item.get('sources', []):
                if source not in group['sources']:
                    group['sources'].append(source)
            group['occurrences'].append({'page': page, 'report': report_path, 'diagnostic': item['id'],
                'state': item.get('state_id', 'initial'), 'frame': item.get('frame_id'),
                'bounds': item.get('bounds'), 'evidence': item.get('evidence', {}),
                'source_precision': item.get('source_precision', []),
                'freshness': value.get('freshness', {}).get('status', 'unknown')})
    for group in groups.values():
        group['occurrence_count'] = len(group['occurrences'])
        group['pages'] = sorted({o['page'] for o in group['occurrences']})
        group['editable_location'] = any(s.get('file') and s.get('line') for s in group['sources'])
    return sorted(groups.values(), key=lambda g: (g['priority'], -len(g['pages']), -g['occurrence_count'], g['id']))


def load_reports(folder):
    folder = Path(folder)
    aggregate = json.loads((folder / 'verification.json').read_text())
    def read(path):
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            return {'status': 'failed', 'freshness': {'status': 'unknown'}, 'diagnostics': [],
                    'render_health': {'status': 'failed', 'errors': [{'type': 'missing_report', 'message': str(error)}]}}
        value['_children'] = {kind + ':' + child['id']: read(path.parent / child['report'])
                              for kind in ('states', 'frames') for child in value.get(kind, [])}
        return value
    return [(row['page'], row['report'], read(folder / row['report']))
            for row in aggregate['pages']]


def write_queue(folder):
    folder = Path(folder)
    reports = load_reports(folder)
    groups = queue(reports)
    blockers = []
    def collect(page, path, value):
        if value.get('status') in ('failed', 'incomplete') or value.get('freshness', {}).get('status') != 'current':
            blockers.append({'page': page, 'scope': path, 'status': value.get('status'),
                'freshness': value.get('freshness', {}), 'render_health': value.get('render_health', {})})
        for key, child in value.get('_children', {}).items():
            collect(page, path + '/' + key, child)
    for page, path, report in reports:
        collect(page, path, report)
    value = {'schema_version': 1, 'coverage_blockers': blockers, 'groups': groups, 'diagnostic_count': sum(g['occurrence_count'] for g in groups),
             'group_count': len(groups), 'visual_review': False}
    (folder / 'triage.json').write_text(json.dumps(value, indent=2, ensure_ascii=False))
    lines = ['# Problems by source line', '',
             f"{value['diagnostic_count']} occurrences → {len(groups)} source groups; {len(blockers)} coverage blockers. Visual review remains required.", '',
             '| Priority | Category | Type | Occurrences | Source | Evidence |', '|---|---|---|---:|---|---|']
    for g in groups:
        source = ', '.join(f"{s.get('file')}:{s.get('line') or '?'}" for s in g['sources'])
        o = g['occurrences'][0]
        lines.append(f"| {g['priority']} | {g['category']} | {g['type']} | {g['occurrence_count']} | {source.replace('|', '&#124;')} | [report]({o['report']}) |")
    (folder / 'triage.md').write_text('\n'.join(lines) + '\n')
    return value
