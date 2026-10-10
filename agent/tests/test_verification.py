from agent.verification import report


def layout(health=None, collision=True):
    return {'source': 'src/s/index.html.j2', 'blocks': [
        {'id': 1, 'source': 'src/s/index.html.j2:4', 'line': 4, 'kind': 'text',
         'box': {'x': 10, 'y': 10, 'w': 100, 'h': 50}},
        {'id': 2, 'source': 'src/s/index.html.j2:8', 'line': 8, 'kind': 'image',
         'box': {'x': 40, 'y': 10, 'w': 100, 'h': 50}}],
        'analysis': {'collisions': [{'a': 1, 'b': 2, 'x0': 40, 'y0': 10,
                                   'x1': 110, 'y1': 60, 'area': 3500}] if collision else []},
        'render_health': health or {'status': 'ready', 'errors': [], 'unchecked': []}}


def test_health_takes_precedence_and_unknown_never_passes():
    assert report(layout(collision=False))['status'] == 'pass'
    assert report(layout())['status'] == 'issues'
    for status in ('incomplete', 'failed'):
        assert report(layout({'status': status, 'errors': []}, False))['status'] == status
    assert report(layout({'status': 'ready', 'unchecked': [{'type': 'iframe'}]}, False))['status'] == 'incomplete'
    value = layout(collision=False)
    del value['render_health']
    assert report(value)['status'] == 'incomplete'


def test_structured_changes_and_source_evidence():
    before = layout()
    after = layout(collision=False)
    value = report(after, before)
    assert len(value['changes']['resolved']) == 1
    assert not value['changes']['introduced']
    finding = value['changes']['resolved'][0]
    assert finding['sources'][0] == {'file': 'src/s/index.html.j2', 'line': 4}
    assert finding['bounds']['x0'] == 40
    assert report(before)['changes']['baseline_available'] is False
    before['blocks'][0]['signature'] = 'changed text'
    assert report(before, layout())['changes']['persisting']


def test_design_lint_is_reviewable_and_has_source():
    value = layout(collision=False)
    value['analysis']['lint'] = [{'kind': 'font-size', 'line': 12, 'advice': 'Use small::'}]
    result = report(value)
    assert result['status'] == 'issues'
    finding = result['diagnostics'][0]
    assert finding['severity'] == 'warning'
    assert finding['sources'] == [{'file': 'src/s/index.html.j2', 'line': 12}]
    assert finding['evidence']['advice'] == 'Use small::'


def test_updated_evidence_keeps_diagnostic_identity():
    before, after = layout(), layout()
    after['analysis']['collisions'][0]['area'] = 1500
    result = report(after, before)['changes']
    assert not result['introduced'] and not result['resolved']
    assert len(result['updated']) == 1


def test_verify_forces_image_artifacts():
    from agent.report import options
    assert options({'images': False})['images'] is True


def test_truncated_internal_measurement_cannot_pass():
    value = layout(collision=False)
    value['internal_measurement'] = {'truncated': True, 'measured': 400, 'limit': 400}
    result = report(value)
    assert result['status'] == 'incomplete'
    assert result['internal_measurement']['truncated']
