"""Tests of the style profile (tools/style_profile.py) on synthetic
measurements and sources: no browser needed."""

import importlib.util
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
spec = importlib.util.spec_from_file_location('style_profile', os.path.join(ROOT, 'tools', 'style_profile.py'))
style_profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(style_profile)

AREA = {'x': 32, 'y': 32, 'w': 1856, 'h': 1016}


def rect(x, y, w, h, t):
    return {'x': x, 'y': y, 'w': w, 'h': h, 't': t}


def block(id, kind, rects, words=0, font=35, position='static', code_lines=0, signature=None):
    return {'id': id, 'kind': kind, 'signature': signature or f'div #{id}', 'ink': rects,
            'box': rects[0], 'visual': rects[0], 'position': position, 'font_size': font,
            'margin': [0, 0, 0, 0], 'media': [], 'overflow': 'visible', 'scroll': None,
            'text': {'words': words, 'formulas': 0, 'code_lines': code_lines, 'items': 0, 'min_font': font}}


def title():
    return block(1, 'title', [rect(62, 58, 600, 70, 'text')], words=3, font=70, signature='h1 "Title"')


def layout(*blocks):
    return {'area': AREA, 'blocks': list(blocks)}


def kind_of(l):
    return style_profile.classify(style_profile.slide_features(l), l['area'])


def test_section_slide():
    big = block(1, 'div', [rect(600, 400, 700, 100, 'text')], words=4, font=91)
    assert kind_of(layout(big)) == 'section'


def test_text_left_media_right():
    text = block(2, 'list', [rect(112, 160, 800, 400, 'text')], words=60)
    image = block(3, 'image', [rect(1200, 150, 600, 450, 'media')], position='fixed')
    l = layout(title(), text, image)
    assert kind_of(l) == 'text_left_media_right'
    f = style_profile.slide_features(l)
    assert f['fixed_media'] == 1 and f['media_items'] == 1


def test_text_then_media():
    text = block(2, 'list', [rect(112, 160, 1500, 200, 'text')], words=40)
    image = block(3, 'image', [rect(500, 420, 900, 500, 'media')])
    assert kind_of(layout(title(), text, image)) == 'text_then_media'


def test_comparison_columns():
    # a sentence across the slide, then two columns of figure + caption
    intro = block(2, 'text', [rect(112, 160, 1400, 40, 'text')], words=20)
    left = block(3, 'div', [rect(200, 250, 600, 400, 'media'), rect(250, 670, 500, 80, 'text')], words=15)
    right = block(4, 'div', [rect(1000, 250, 600, 400, 'media'), rect(1050, 670, 500, 80, 'text')], words=15)
    assert kind_of(layout(title(), intro, left, right)) == 'columns'


def test_media_row_and_code():
    images = [block(i, 'image', [rect(100 + 450 * (i - 2), 300, 400, 300, 'media')]) for i in range(2, 6)]
    assert kind_of(layout(title(), *images)) == 'media_row'
    code = block(2, 'code', [rect(112, 160, 900, 500, 'paint'), rect(120, 170, 600, 30, 'text')],
                 code_lines=12)
    text = block(3, 'text', [rect(1100, 160, 700, 200, 'text')], words=40)
    assert kind_of(layout(title(), code, text)) == 'text_code'


def test_source_idioms(tmp_path):
    source = tmp_path / 'index.html.j2'
    source.write_text('= Title\n\n* item \\(x\\)\n** sub\n\ndiv::[height:25px;]::\n\n'
                      'code::[c++]\nstd::vector<int> v;\n::\n\n'
                      '::[position:fixed; top:150px; left:1100px;]\nimg::a.png[width:500px;]\n::\n')
    idioms = style_profile.source_idioms([str(source)])
    assert idioms['spacers'] == {'25px': 1}
    assert idioms['tags']['code'] == 1 and 'std' not in idioms['tags']
    assert idioms['values'][('position', 'fixed')] == 1 and idioms['values'][('width', '500px')] == 1
    assert idioms['line_starts'] == {'=': 1, '*': 1, '**': 1}
    assert idioms['inline_math'] == 1
