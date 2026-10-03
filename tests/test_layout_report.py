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
    assert layout_report.find_collisions(blocks) == [{'a': 1, 'b': 2, 'x0': 50, 'y0': 60, 'x1': 100, 'y1': 100}]


def test_touching_or_tiny_overlap_is_not_a_collision():
    blocks = [block(1, 0, 0, 100, 100), block(2, 100, 0, 100, 100), block(3, 0, 97, 100, 50)]
    assert layout_report.find_collisions(blocks, threshold=4) == []


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
             {'src': 'b.png', 'w': 100, 'h': 100, 'natural_w': 200, 'natural_h': 200}]
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
    assert '| content/a | 1 | 1 | 0 | 0 | 0 |' in summary
