import pytest
from lib.design_checks import analyse_design


def node(id, design_role, font=36, words=8, **extra):
    box = {'x': 0, 'y': 100, 'w': 200, 'h': 50}
    return {'id': id, 'design_role': design_role, 'font_size': font, 'text': {'words': words, 'min_font': font},
            'box': box, 'visual': box, 'ink': [dict(box, t='text')],
            'source': f'src/slide.html.j2:{id[1:]}', 'line': int(id[1:]), 'stable_id': id, **extra}


def layout(*nodes):
    return {'subblocks': list(nodes), 'blocks': [], 'viewport': {'w': 1920, 'h': 1080},
            'design_measurement': {'roles': True}, 'layout_name': 'flow',
            'render_health': {'status': 'ready', 'errors': [], 'unchecked': []}}


def test_caption_reference_and_body_have_distinct_legibility_limits():
    value = layout(node('s1', 'title', 72), node('s2', 'body', 36),
                   node('s3', 'caption', 16), node('s4', 'reference', 12), node('s5', 'body', 16))
    findings, _ = analyse_design(value)
    assert [(d['id'], d['kind']) for d in findings] == [('s5', 'font_min')]


def test_hierarchy_and_wrapped_title_have_reviewable_source_evidence():
    value = layout(node('s1', 'title', 36, design_lines=3), node('s2', 'body', 36), node('s3', 'caption', 48))
    findings, metadata = analyse_design(value)
    assert {d['kind'] for d in findings} == {'title_hierarchy', 'title_lines', 'caption_hierarchy'}
    assert metadata['enabled']


def test_named_layout_overrides_and_disabled_checks():
    value = layout(node('s1', 'body', 16))
    value['layout_name'] = 'section'
    assert analyse_design(value)[0]
    assert not analyse_design(value, {'layouts': {'section': {'body': {'min_font': 14}}}})[0]
    value['layout_name'] = 'flow'
    assert analyse_design(value, {'layouts': {'section': {'body': {'min_font': 14}}}})[0]
    assert not analyse_design(value, {'roles': {'body': {'min_font': None}}})[0]
    assert not analyse_design(value, {'enabled': False})[0]


def test_figure_caption_distance_uses_local_container_and_media_box():
    parent = node('s1', 'body', words=0, role='column')
    figure = node('s2', 'figure', words=0, parent='s1', box={'x': 0, 'y': 100, 'w': 200, 'h': 100})
    caption = node('s3', 'caption', 16, parent='s1', visual={'x': 0, 'y': 300, 'w': 150, 'h': 20})
    findings, _ = analyse_design(layout(parent, figure, caption))
    assert [(d['kind'], d['value'], d['by']) for d in findings] == [('caption_gap', 100, 's2')]
    caption['parent'] = None
    assert not analyse_design(layout(parent, figure, caption))[0]  # no speculative association
    figure['box']['h'] = 20
    assert analyse_design(layout(parent, figure))[0][0]['kind'] == 'figure_size'
    figure['design_role'] = 'decorative'
    assert not analyse_design(layout(parent, figure))[0]


def test_thresholds_scale_with_capture_width():
    value = layout(node('s1', 'body', 16))
    value['viewport']['w'] = 960
    assert not analyse_design(value)[0]


@pytest.mark.parametrize('spec', [{'roles': {'boddy': {}}}, {'roles': {'body': {'min_font': -1}}},
                                  {'layouts': []}, {'roles': {'body': {'min_font': True}}},
                                  {'enabled': 'false'}, {'roles': {'title': {'min_font': float('nan')}}}])
def test_invalid_configuration_fails_instead_of_silently_ignoring_rules(spec):
    with pytest.raises(ValueError, match='design_rules'):
        analyse_design(layout(), spec)
