"""Tests of the layout analysis (plugins/layout_report.py), on synthetic
measurements: no browser needed."""

import importlib.util
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
spec = importlib.util.spec_from_file_location('layout_report', os.path.join(ROOT, 'plugins', 'layout_report.py'))
layout_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout_report)

AREA = {'x': 0, 'y': 0, 'w': 1000, 'h': 500}


def block(id, x, y, w, h, kind='div', position='static', **extra):
    rect = {'x': x, 'y': y, 'w': w, 'h': h}
    return {'id': id, 'kind': kind, 'signature': f'div #{id}', 'box': rect, 'visual': rect,
            'position': position, 'margin': [0, 0, 0, 0], 'font_size': 20,
            'overflow': 'visible', 'scroll': None, 'media': [], **extra}


def test_collision_with_overlap_rectangle():
    blocks = [block(1, 0, 0, 100, 100), block(2, 50, 60, 100, 100, position='fixed')]
    assert layout_report.find_collisions(blocks) == [{'a': 1, 'b': 2, 'x0': 50, 'y0': 60, 'x1': 100, 'y1': 100,
                                                      'area': 2000}]


def test_touching_or_tiny_overlap_is_not_a_collision():
    blocks = [block(1, 0, 0, 100, 100), block(2, 100, 0, 100, 100), block(3, 0, 97, 100, 50)]
    assert layout_report.find_collisions(blocks, threshold=4) == []


def test_empty_corner_of_an_irregular_block_is_not_a_collision():
    # L-shaped text: a long first line, then short lines; a fixed image sits
    # to the right of the short lines, inside the bounding rectangle
    text = block(1, 0, 0, 800, 120, ink=[{'x': 0, 'y': 0, 'w': 800, 'h': 40},
                                         {'x': 0, 'y': 40, 'w': 300, 'h': 80}])
    image = block(2, 400, 50, 300, 200, position='fixed')
    assert layout_report.find_collisions([text, image]) == []
    image_over_text = block(3, 250, 60, 300, 100, position='fixed')
    collisions = layout_report.find_collisions([text, image_over_text])
    assert collisions == [{'a': 1, 'b': 3, 'x0': 250, 'y0': 60, 'x1': 300, 'y1': 120, 'area': 3000}]


def test_overlap_with_image_background_only_is_a_note():
    content = {'x': 600, 'y': 100, 'w': 200, 'h': 200}
    media = [{'src': 'tri.png', 'w': 400, 'h': 400, 'natural_w': 800, 'natural_h': 800,
              'box': {'x': 500, 'y': 0, 'w': 400, 'h': 400}, 'content': content}]
    image = block(1, 600, 100, 200, 200, kind='image', media=media, ink=[content])
    text = block(2, 0, 20, 550, 40)
    layout = {'area': AREA, 'blocks': [image, text]}
    analysis = layout_report.analyse(layout)
    assert analysis['collisions'] == []
    assert analysis['background_overlaps'] == [{'image': 1, 'other': 2, 'src': 'tri.png'}]
    md = layout_report.page_markdown('p', 'src/p/index.html.j2', layout)
    assert '#2 overlaps only the background' in md


def test_out_of_area_sides():
    out = layout_report.find_out_of_area([block(1, -20, 480, 1100, 40)], AREA)
    assert out == [{'id': 1, 'left': 20, 'right': 80, 'bottom': 20}]


def test_scrolling_page_bottom_not_checked():
    out = layout_report.find_out_of_area([block(1, -20, 480, 100, 900)], AREA, scrolling=True)
    assert out == [{'id': 1, 'left': 20}]


def test_clipped_content_only_when_overflow_hidden():
    scroll = {'w': 100, 'h': 300, 'client_w': 100, 'client_h': 200}
    visible = block(1, 0, 0, 100, 200, scroll=scroll)
    hidden = block(2, 0, 0, 100, 200, scroll=scroll)
    hidden['overflow'] = 'hidden'
    assert layout_report.find_clipped([visible, hidden]) == [{'id': 2, 'w': 0, 'h': 100}]


def test_upscaled_image():
    media = [{'src': 'a.png', 'w': 400, 'h': 200, 'natural_w': 200, 'natural_h': 100},
             {'src': 'b.png', 'w': 100, 'h': 100, 'natural_w': 200, 'natural_h': 200},
             {'src': 'c.png', 'w': 220, 'h': 100, 'natural_w': 200, 'natural_h': 100},   # ×1.1: not visible
             {'src': 'd.svg', 'w': 800, 'h': 400, 'natural_w': 200, 'natural_h': 100, 'vector': True}]
    assert layout_report.find_upscaled_images([block(1, 0, 0, 400, 200, media=media)]) == \
        [{'id': 1, 'src': 'a.png', 'scale': 2.0}]


def test_vertical_gaps_ignore_positioned_blocks():
    blocks = [block(1, 0, 0, 100, 50), block(2, 0, 400, 100, 50, position='fixed'), block(3, 0, 80, 100, 20)]
    assert layout_report.vertical_gaps(blocks) == [(1, 3, 30)]


def test_spacers_are_ignored_by_the_analysis():
    layout = {'area': AREA, 'blocks': [block(1, 0, 0, 100, 100), block(2, 0, 0, 1000, 600, kind='spacer')]}
    analysis = layout_report.analyse(layout)
    assert analysis['collisions'] == [] and analysis['out_of_area'] == []


def test_occupancy():
    layout = {'area': AREA, 'blocks': [block(1, 0, 0, 500, 500)]}
    assert layout_report.analyse(layout)['occupancy'] == 0.5


def test_markdown_report_and_summary():
    layout = {'area': AREA, 'blocks': [block(1, 0, 0, 100, 100), block(2, 50, 50, 100, 100, position='fixed')]}
    layout_report.analyse(layout)
    md = layout_report.page_markdown('content/a', 'src/content/a/index.html.j2', layout)
    assert '| 2 | div | 50, 50 | 100 × 100 |' in md
    assert 'COLLISION #1 × #2' in md
    summary = layout_report.summary_markdown([('content/a', 'content/a/layout.md', layout['analysis'])])
    assert '| content/a | 1 | 0 | 1 | 0 | 0 | 0 | 0 |' in summary


def text(x, y, w, h):
    return {'x': x, 'y': y, 'w': w, 'h': h, 't': 'text'}


def test_text_on_background_of_another_block_is_not_a_collision():
    code = block(1, 0, 0, 800, 300, kind='code', ink=[{'x': 0, 'y': 0, 'w': 800, 'h': 300, 't': 'paint'},
                                                      text(10, 10, 300, 30)])
    note = block(2, 400, 10, 300, 40, position='fixed', ink=[text(400, 10, 300, 40)])
    collisions, tight, intentional = layout_report.find_overlaps([code, note])
    assert collisions == tight == intentional == []


def test_shallow_text_overlap_is_tight():
    title = block(1, 0, 0, 500, 50, kind='title', ink=[text(0, 0, 500, 50)], font_size=40)
    formula = block(2, 0, 42, 500, 60, ink=[text(0, 42, 500, 60)], font_size=35)
    collisions, tight, _ = layout_report.find_overlaps([title, formula])
    assert collisions == [] and [(t['a'], t['b']) for t in tight] == [(1, 2)]
    deep = block(3, 0, 10, 500, 60, ink=[text(0, 10, 500, 60)], font_size=35)
    collisions, tight, _ = layout_report.find_overlaps([title, deep])
    assert [(c['a'], c['b']) for c in collisions] == [(1, 3)] and tight == []


def test_intentional_overlay():
    image = block(1, 0, 0, 600, 300, kind='image', ink=[{'x': 0, 'y': 0, 'w': 600, 'h': 300, 't': 'media'}])
    zoom = block(2, 400, 200, 200, 200, kind='image', position='fixed', intentional=True,
                 ink=[{'x': 400, 'y': 200, 'w': 200, 'h': 200, 't': 'media'}])
    layout = {'area': AREA, 'blocks': [image, zoom]}
    analysis = layout_report.analyse(layout)
    assert analysis['collisions'] == [] and [(c['a'], c['b']) for c in analysis['intentional']] == [(1, 2)]
    assert layout_report.count_problems(analysis) == 0
    assert 'marked as intentional' in layout_report.page_markdown('p', 's', layout)


def test_hidden_text_is_a_problem():
    sentence = block(1, 0, 0, 900, 40, ink=[text(0, 0, 900, 40)],
                     hidden_text=[{'by': 2, 'x': 600, 'y': 0, 'w': 300, 'h': 40, 'samples': 15, 'total': 50}])
    image = block(2, 600, 0, 300, 100, kind='image', position='fixed',
                  ink=[{'x': 650, 'y': 0, 'w': 100, 'h': 100, 't': 'media'}])
    layout = {'area': AREA, 'blocks': [sentence, image]}
    analysis = layout_report.analyse(layout)
    assert analysis['hidden_text'] == [{'id': 1, 'by': 2, 'x0': 600, 'y0': 0, 'x1': 900, 'y1': 40, 'fraction': 0.3}]
    md = layout_report.page_markdown('p', 's', layout)
    assert 'HIDDEN TEXT #1 under #2' in md and '30 % of the text of #1' in md
    # the overlap of the text with the image content is not reported again as a collision
    assert analysis['collisions'] == []
