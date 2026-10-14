import pytest
from agent.interactive import options_for
from agent.verification import report


def test_matching_scenarios_and_budget():
    spec = {'max_states': 2, 'pages': {'a/*': [{'name': 'reveal', 'actions': [{'type': 'click', 'selector': '#button'}]}]}}
    assert options_for(spec, 'a/index.html', True)['plans'][0]['name'] == 'reveal'
    assert not options_for(spec, 'b/index.html', True)['plans']
    assert options_for(spec, 'a/index.html', True)['enabled']
    assert not options_for({}, 'a/index.html')['enabled']


@pytest.mark.parametrize('spec', [{'max_states': 0}, {'auto_media': 'true'},
    {'pages': {'*': [{'name': '../escape'}]}}, {'pages': {'*': [{'name': 'auto-mid'}]}},
    {'pages': {'*': [{'name': 'x', 'time_ms': 99999}]}},
    {'pages': {'*': [{'name': 'x', 'actions': [{'type': 'eval', 'selector': '#x'}]}]}},
    {'pages': {'*': [{'name': 'x', 'expect': [{'selector': '#x', 'visible': 1}]}]}},
    {'pages': {'*': [{'name': 'x'}], 'a/*': [{'name': 'x'}]}}])
def test_invalid_plans_fail_early(spec):
    with pytest.raises(ValueError, match='interactive'):
        options_for(spec, 'a/index.html', True)


def test_failed_and_truncated_states_cannot_pass():
    base = {'blocks': [], 'analysis': {}, 'render_health': {'status': 'ready'}}
    assert report(base)['status'] == 'pass'
    base['interactive'] = {'truncated': True, 'states': []}
    assert report(base)['status'] == 'incomplete'
    base['interactive'] = {'states': [{'id': 'missing', 'status': 'failed'}]}
    assert report(base)['status'] == 'failed'


def test_state_and_frame_diagnostics_have_separate_identities_and_bounds():
    child = {'blocks': [{'id': 1, 'stable_id': 'text', 'source': 'a:1', 'box': {'x': 0, 'y': 0, 'w': 50, 'h': 20}}],
             'analysis': {'clipped': [{'id': 1, 'w': 30, 'h': 0}]}, 'viewport': {'w': 100, 'h': 100},
             'render_health': {'status': 'ready'}}
    root = {'blocks': [], 'analysis': {}, 'render_health': {'status': 'ready'},
            'interactive': {'states': [{'id': 'later', 'status': 'measured', 'layout': child}]},
            'frame_layouts': [{'id': 'f1', 'box': {'x': 200, 'y': 100, 'width': 100, 'height': 100}, 'layout': child}]}
    items = report(root)['diagnostics']
    assert len({d['id'] for d in items}) == 2
    assert items[0]['frame_id'] == 'f1' and items[0]['bounds']['x0'] == 200
    assert items[1]['state_id'] == 'later' and items[1]['bounds']['x0'] == 0
