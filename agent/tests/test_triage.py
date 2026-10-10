from agent.triage import queue, group_key


def finding(**kw):
    return dict({'id': 'collision:1', 'type': 'collisions', 'severity': 'error',
                 'method': 'deterministic_geometry', 'block_anchors': ['B', 'A'],
                 'sources': [{'file': 'src/s/index.html.j2', 'line': 4}], 'evidence': {'area': 10}}, **kw)


def report(items):
    return {'diagnostics': items, 'freshness': {'status': 'current'}}


def test_group_repeated_pages_states_and_preserve_evidence():
    initial = finding()
    later = finding(id='state:later:collision:1', state_id='later', bounds={'x0': 2}, evidence={'area': 20})
    groups = queue([('s', 'pages/s/verification.json', report([initial, later])),
                    ('repeat', 'pages/repeat/verification.json', report([initial]))])
    assert len(groups) == 1
    assert groups[0]['occurrence_count'] == 3
    assert groups[0]['pages'] == ['repeat', 's']
    assert groups[0]['occurrences'][1]['state'] == 'later'
    assert groups[0]['occurrences'][1]['evidence']['area'] == 20
    assert groups[0]['category'] == 'measured_defect'


def test_distinguish_documents_rules_and_candidates():
    a = finding()
    b = finding(sources=[{'file': 'src/s/assets/app.html', 'line': None}])
    assert group_key(a) != group_key(b)
    c = finding(type='role_design', method='role_design_rule', evidence={'kind': 'font_min', 'role': 'body'})
    d = finding(type='role_design', method='role_design_rule', evidence={'kind': 'font_min', 'role': 'caption'})
    assert group_key(c) != group_key(d)
    canvas = finding(type='canvas_overlaps', method='unverified_raster_overlap', severity='warning')
    groups = queue([('s', 'r', report([canvas, c, a]))])
    assert [g['category'] for g in groups] == ['measured_defect', 'review_rule', 'visual_candidate']


def test_missing_report_becomes_explicit_coverage_blocker(tmp_path):
    import json
    from agent.triage import write_queue
    (tmp_path / 'verification.json').write_text(json.dumps({'pages': [{'page': 'missing', 'report': 'missing.json'}]}))
    value = write_queue(tmp_path)
    assert value['group_count'] == 0
    assert value['coverage_blockers'][0]['status'] == 'failed'
    assert value['coverage_blockers'][0]['render_health']['errors'][0]['type'] == 'missing_report'


def test_lint_group_survives_inserted_lines():
    a = finding(type='lint', method='source_lint', block_anchors=[], evidence={'source_anchor': 'persistent', 'kind': 'font-size'})
    b = dict(a, sources=[{'file': 'src/s/index.html.j2', 'line': 50}])
    assert group_key(a) == group_key(b)
