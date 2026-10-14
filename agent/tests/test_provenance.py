import json
import re
from pathlib import Path

import lhtml
from jinja2 import Environment, FileSystemLoader
from lib.tracking import TrackingLoader, lhtml_includes
from lib import source_map
from agent.provenance import SourceRegistry, apply_provenance
from agent.verification import report


def test_persistent_anchors_insert_edit_move_and_reload(tmp_path):
    path = tmp_path / 'page.html.j2'
    registry = SourceRegistry(tmp_path, set())
    registry.instrument('= Title\n\nUnique text\n\nOther text', path)
    anchors = {row['text']: row['id'] for row in registry.files['page.html.j2']}
    registry.save()
    registry = SourceRegistry(tmp_path, set())
    registry.instrument('\n= Changed title\n\nOther text\n\nUnique text', path)
    rows = {row['text']: row['id'] for row in registry.files['page.html.j2']}
    assert rows['Unique text'] == anchors['Unique text']
    assert rows['Other text'] == anchors['Other text']
    # Isolate a one-to-one text edit, with surrounding context unchanged.
    registry.instrument('\n= Changed title\n\nOther text\n\nEdited text', path)
    assert registry.files['page.html.j2'][-1]['id'] == rows['Unique text']


def test_jinja_include_and_nested_provenance(tmp_path):
    main = tmp_path / 'main.html.j2'
    include = tmp_path / 'part.html.j2'
    main.write_text('= Main\n{% include "part.html.j2" %}\n')
    include.write_text('div::\n* First\n* Second\n::\n')
    registry = SourceRegistry(tmp_path, set())
    loader = TrackingLoader(FileSystemLoader(tmp_path), registry, [tmp_path])
    text = Environment(loader=loader).get_template('main.html.j2').render()
    html = apply_provenance('<body>' + lhtml.run(text) + '</body>', registry)
    assert 'data-lhtml-src="part.html.j2:1"' in html
    assert 'data-lhtml-src="part.html.j2:2"' in html
    assert '&quot;end_line&quot;: 3' in html
    assert source_map.OPEN not in html
    assert str(include) in loader.used
    assert 'data-lhtml-id=' in html


def test_lhtml_include_origin_and_code_preservation(tmp_path):
    part = tmp_path / 'part.lhtml'
    part.write_text('div::\n* Included item\n::\n')
    registry = SourceRegistry(tmp_path, {'include'})
    text = registry.instrument('include::part.lhtml\n', tmp_path / 'main.html.j2')
    used = set()
    with lhtml_includes(registry, used):
        html = lhtml.run(text, {'directory_include': [str(tmp_path)]})
    output = apply_provenance('<body>' + html + '</body>', registry)
    assert 'data-lhtml-src="part.lhtml:1"' in output
    assert str(part) in used
    from lhtml import process
    original = process.process_include_recursive
    try:
        with lhtml_includes(registry, set()):
            raise RuntimeError('conversion failed')
    except RuntimeError:
        pass
    assert process.process_include_recursive is original


def test_diagnostic_identity_survives_line_shift():
    def value(line):
        return {'source': 'main', 'blocks': [{'id': 1, 'stable_id': 'anchor:h1:1',
                'source': f'main:{line}', 'line': line}],
                'analysis': {'out_of_area': [{'id': 1, 'left': 10}]},
                'render_health': {'status': 'ready'}}
    changes = report(value(12), value(2))['changes']
    assert len(changes['persisting']) == 1
    assert not changes['introduced'] and not changes['resolved']


def test_lhtml_frontmatter_keeps_original_line_numbers(tmp_path):
    part = tmp_path / 'part.lhtml'
    part.write_text('---\ntitle: Part\n---\n= Included\n')
    registry = SourceRegistry(tmp_path, {'include'})
    with lhtml_includes(registry, set()):
        result = lhtml.run(registry.instrument('include::part.lhtml\n', tmp_path / 'main'),
                           {'directory_include': [str(tmp_path)]})
    assert 'data-lhtml-src="part.lhtml:4"' in apply_provenance(result, registry)


def test_code_block_has_full_range_without_changing_code(tmp_path):
    registry = SourceRegistry(tmp_path, set())
    text = 'code::[python]\nx = 1\ny = 2\ncode::[-]\n'
    marked = registry.instrument(text, tmp_path / 'main.html.j2')
    assert source_map.strip(lhtml.run(marked)) == lhtml.run(text)
    html = apply_provenance(lhtml.run(marked), registry)
    assert 'data-lhtml-src="main.html.j2:1"' in html
    assert '&quot;end_line&quot;: 4' in html


def test_free_text_provenance_does_not_add_layout_elements(tmp_path):
    registry = SourceRegistry(tmp_path, set())
    text = registry.instrument('= Title\n\nPlain text\n', tmp_path / 'main.html.j2')
    html = apply_provenance('<body>' + lhtml.run(text) + '</body>', registry)
    assert 'data-lhtml-free-text=' in html
    assert '&quot;source&quot;: &quot;main.html.j2:3&quot;' in html
    assert '<span' not in html
