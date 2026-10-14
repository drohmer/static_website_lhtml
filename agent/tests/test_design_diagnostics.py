from lib.design_checks import analyse_design
from agent.verification import report


def node(id, design_role, font=36, words=8, **extra):
    box = {'x': 0, 'y': 100, 'w': 200, 'h': 50}
    return {'id': id, 'design_role': design_role, 'font_size': font, 'text': {'words': words, 'min_font': font},
            'box': box, 'visual': box, 'ink': [dict(box, t='text')],
            'source': f'src/slide.html.j2:{id[1:]}', 'line': int(id[1:]), 'stable_id': id, **extra}


def test_role_design_findings_become_reviewable_diagnostics():
    value = {'subblocks': [node('s1', 'title', 36, design_lines=3), node('s2', 'body', 36), node('s3', 'caption', 48)],
             'blocks': [], 'viewport': {'w': 1920, 'h': 1080}, 'design_measurement': {'roles': True},
             'layout_name': 'flow', 'render_health': {'status': 'ready', 'errors': [], 'unchecked': []}}
    findings, metadata = analyse_design(value)
    value['analysis'] = {'role_design': findings}
    value['design_checks'] = metadata
    result = report(value)
    assert result['checks']['role_design']
    assert all(d['method'] == 'role_design_rule' and d['sources'] and d['bounds'] for d in result['diagnostics'])
    assert result['status'] == 'issues'
