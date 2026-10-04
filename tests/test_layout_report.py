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


def find_collisions(blocks, threshold=4):
    """Pairs of blocks whose drawn content overlaps."""
    return layout_report.find_overlaps(blocks, threshold)[0]


def test_collision_with_overlap_rectangle():
    blocks = [block(1, 0, 0, 100, 100), block(2, 50, 60, 100, 100, position='fixed')]
    assert find_collisions(blocks) == [{'a': 1, 'b': 2, 'x0': 50, 'y0': 60, 'x1': 100, 'y1': 100,
                                                      'area': 2000}]


def test_touching_or_tiny_overlap_is_not_a_collision():
    blocks = [block(1, 0, 0, 100, 100), block(2, 100, 0, 100, 100), block(3, 0, 97, 100, 50)]
    assert find_collisions(blocks, threshold=4) == []


def test_empty_corner_of_an_irregular_block_is_not_a_collision():
    # L-shaped text: a long first line, then short lines; a fixed image sits
    # to the right of the short lines, inside the bounding rectangle
    text = block(1, 0, 0, 800, 120, ink=[{'x': 0, 'y': 0, 'w': 800, 'h': 40},
                                         {'x': 0, 'y': 40, 'w': 300, 'h': 80}])
    image = block(2, 400, 50, 300, 200, position='fixed')
    assert find_collisions([text, image]) == []
    image_over_text = block(3, 250, 60, 300, 100, position='fixed')
    collisions = find_collisions([text, image_over_text])
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
    assert '| 2 | - | div | 50, 50 | 100 × 100 |' in md
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


def paint(x, y, w, h):
    return {'x': x, 'y': y, 'w': w, 'h': h, 't': 'paint'}


def test_near_alignment_of_frames_and_text_left_edges():
    # two framed boxes stacked: right edges 6 px apart
    code = block(1, 100, 100, 700, 200, ink=[paint(100, 100, 700, 200)])
    image = block(2, 100, 350, 694, 300, ink=[paint(100, 350, 694, 300)])
    near = layout_report.find_near_alignments([code, image], AREA)
    assert near == [{'id': 1, 'axis': 'x', 'edge': 'right', 'value': 800, 'ref': 794,
                     'ref_label': 'right of #2', 'delta': 6}]
    # left-aligned text 7 px off a column of the deck
    para = block(3, 159, 700, 400, 40, ink=[text(159, 700, 400, 40)])
    near = layout_report.find_near_alignments([para], {'x': 0, 'y': 0, 'w': 1000, 'h': 1000}, grid=[152])
    assert [(n['id'], n['edge'], n['ref_label'], n['delta']) for n in near] == [(3, 'left', 'deck column', 7)]


def test_ragged_text_edges_and_line_boxes_are_not_compared():
    # right end of left-aligned text, left end of centered text, top of line boxes
    a = block(1, 100, 100, 400, 40, ink=[text(100, 100, 400, 40)])
    b = block(2, 100, 200, 405, 40, ink=[text(100, 200, 405, 40)])
    centered = block(3, 306, 300, 200, 40, ink=[text(306, 300, 200, 40)], text_align='center')
    framed = block(4, 300, 400, 210, 100, ink=[paint(300, 400, 210, 100)])
    side = block(5, 700, 105, 200, 40, ink=[text(700, 105, 200, 40)])
    assert layout_report.find_near_alignments([a, b, centered, framed, side], AREA) == []


def test_image_with_transparent_margin_has_no_precise_edges():
    media = [{'src': 'tri.png', 'box': {'x': 500, 'y': 100, 'w': 300, 'h': 300},
              'content': {'x': 550, 'y': 150, 'w': 200, 'h': 200}}]
    image = block(1, 550, 150, 200, 200, kind='image', media=media,
                  ink=[{'x': 550, 'y': 150, 'w': 200, 'h': 200, 't': 'media'}])
    assert layout_report._precise_edges(image) == {}
    media[0]['content'] = media[0]['box']
    assert set(layout_report._precise_edges(image)) == {'left', 'right', 'center', 'top', 'bottom', 'middle'}


def page(title_y=58, title_font=70, body_font=35, words=30, extra=()):
    title = block(1, 62, title_y, 600, 70, kind='title', font_size=title_font, ink=[text(62, title_y, 600, 70)])
    title['signature'] = 'h1 "Title"'
    body = block(2, 112, title_y + 100, 800, 200, kind='list', font_size=body_font,
                 ink=[text(112, title_y + 100, 800, 200)], text={'words': words, 'min_font': body_font})
    return {'area': {'x': 32, 'y': 32, 'w': 1856, 'h': 1016}, 'blocks': [title, body, *extra]}


def test_deck_norms_and_deviations():
    deck = [page() for _ in range(5)] + [page(title_y=80), page(body_font=22)]
    norms = layout_report.deck_norms(deck)
    assert norms['titles'] == [{'tag': 'h1', 'font': 70, 'pages': 7, 'x_anchor': 'left', 'x': 62,
                                'y_anchor': 'top', 'y': 58}]
    assert norms['columns'] == [62, 112] and norms['body_font'] == 35 and norms['text_fonts'] == [35]
    assert norms['title_gap'] == 30 and norms['words'] == 30
    assert layout_report.analyse(deck[0], norms=norms)['deviations'] == []
    deviations = layout_report.analyse(deck[5], norms=norms)['deviations']
    assert deviations == [{'kind': 'title_position', 'id': 1, 'value': [62, 80], 'norm': [62, 58],
                           'anchor': ['left', 'top']}]
    deviations = layout_report.analyse(deck[6], norms=norms)['deviations']
    assert deviations == [{'kind': 'text_font', 'id': 2, 'value': 22, 'norm': [35]}]
    assert 'TEXT FONT #2: text at 22 px' in layout_report.page_markdown('p', 's', deck[6])
    assert 'page title `h1` 70 px (7 pages): left x 62, top y 58' in layout_report.norms_markdown(norms)


def test_centered_titles_of_various_lengths():
    deck = []
    for w in (400, 600, 800):
        t = block(1, 960 - w // 2, 500, w, 90, kind='title', font_size=91, ink=[text(960 - w // 2, 500, w, 90)])
        t['signature'] = 'h1 "Section"'
        deck.append({'area': AREA, 'blocks': [t]})
    norms = layout_report.deck_norms(deck)
    assert [(t['x_anchor'], t['x']) for t in norms['titles']] == [('center', 960)]


def test_density_and_warnings():
    blocks = [block(1, 0, 0, 500, 100, ink=[text(0, 0, 500, 50), text(0, 50, 300, 50)],
                    text={'words': 70, 'formulas': 2, 'code_lines': 0, 'items': 3, 'min_font': 35}),
              block(2, 0, 200, 500, 200, kind='code', ink=[paint(0, 200, 500, 200), text(10, 210, 300, 20)],
                    text={'words': 0, 'formulas': 0, 'code_lines': 8, 'items': 0, 'min_font': 17})]
    d = layout_report.density(blocks, AREA)
    assert (d['words'], d['formulas'], d['code_lines'], d['items'], d['text_lines'], d['min_font']) == \
        (70, 2, 8, 3, 2, 17)
    assert layout_report.find_density_warnings(d, max_words=60, min_font=20) == [
        {'kind': 'words', 'value': 70, 'limit': 60}, {'kind': 'min_font', 'value': 17, 'limit': 20}]
    layout = {'area': AREA, 'blocks': blocks}
    analysis = layout_report.analyse(layout, limits={'max_words': 60, 'min_font': 20})
    assert layout_report.count_warnings(analysis) == 2
    md = layout_report.page_markdown('p', 's', layout)
    assert 'DENSE: 70 words' in md and 'SMALL FONT: 17 px' in md and '## Density' in md


def test_contact_sheets():
    analysis = layout_report.analyse({'area': AREA, 'blocks': [block(1, 0, 0, 100, 100),
                                                                block(2, 50, 50, 100, 100)]})
    rows = [(f'p{i}', f'dir/p{i}', analysis) for i in range(20)]
    sheets = layout_report.contact_sheets_html(rows, {'w': 1920, 'h': 1080}, columns=4, rows_per_sheet=4)
    assert len(sheets) == 2 and sheets[0].count('<figure>') == 16 and sheets[1].count('<figure>') == 4
    assert '<img src="dir/p16/render.png"><figcaption><b>17</b> p16 <span class="p">P1</span>' in sheets[1]


def test_deck_without_page_titles():
    deck = [{'area': AREA, 'blocks': [block(1, 10, 10, 300, 40, ink=[text(10, 10, 300, 40)],
                                            text={'words': 5, 'min_font': 20})]} for _ in range(4)]
    norms = layout_report.deck_norms(deck)
    assert norms['titles'] == [] and norms['columns'] == [10]
    assert layout_report.analyse(deck[0], norms=norms)['deviations'] == []


def test_no_density_warnings_on_scrolling_pages():
    blocks = [block(1, 0, 0, 500, 2000, ink=[text(0, 0, 500, 2000)], text={'words': 900, 'min_font': 14})]
    analysis = layout_report.analyse({'area': AREA, 'blocks': blocks, 'scrolling': True})
    assert analysis['dense'] == [] and analysis['density']['words'] == 900


def test_content_over_the_navigation():
    blocks = [block(1, 900, 450, 80, 40), block(2, 0, 0, 100, 100)]
    found = layout_report.find_reserved_overlaps(blocks, [{'x': 880, 'y': 440, 'w': 120, 'h': 60, 'name': 'nav'}])
    assert [(f['id'], f['name']) for f in found] == [(1, 'nav')]


def test_wrapped_titles_and_items():
    b = block(1, 0, 0, 500, 100, wrapped=[
        {'tag': 'h2', 'text': 'A long title', 'lines': 2, 'first_w': 500, 'last_w': 400},
        {'tag': 'li', 'text': 'An item', 'lines': 2, 'first_w': 800, 'last_w': 100},
        {'tag': 'li', 'text': 'A paragraph item', 'lines': 2, 'first_w': 800, 'last_w': 600},
        {'tag': 'li', 'text': 'A long item', 'lines': 3, 'first_w': 800, 'last_w': 100}])
    assert [w['text'] for w in layout_report.find_wrapped([b])] == ['A long title', 'An item']


def test_row_of_figures_not_aligned():
    rows = [{'figures': ['a.png', 'b.png', 'c.png'], 'tops': [363, 363, 377], 'bottoms': [500, 500, 500]},
            {'figures': ['d.png', 'e.png'], 'tops': [100, 101], 'bottoms': [200, 300]}]     # 100 px: deliberate
    found = layout_report.find_row_misalignments([block(1, 0, 0, 10, 10, rows=rows)])
    assert [(f['edge'], f['spread']) for f in found] == [('top', 14)]


def test_figure_small_in_its_box_or_cropped():
    media = [{'src': 'a.png', 'box': {'x': 0, 'y': 0, 'w': 400, 'h': 400}, 'drawn': {'w': 400, 'h': 100, 'fit': 'contain'}},
             {'src': 'b.png', 'box': {'x': 0, 'y': 0, 'w': 400, 'h': 400}, 'drawn': {'w': 600, 'h': 400, 'fit': 'cover'}},
             {'src': 'c.png', 'box': {'x': 0, 'y': 0, 'w': 400, 'h': 400}, 'drawn': {'w': 400, 'h': 380, 'fit': 'contain'}}]
    found = layout_report.find_fit([block(1, 0, 0, 400, 400, media=media)])
    assert [(f['src'], f['kind'], f['sides']) for f in found] == [('a.png', 'small', 'top and bottom'),
                                                                  ('b.png', 'cropped', 'left and right')]


def test_largest_free_rect():
    blocks = [block(1, 0, 0, 1000, 100), block(2, 0, 100, 400, 400)]
    free = layout_report.largest_free_rect(blocks, AREA)
    assert (free['x'], free['y'], free['w'], free['h']) == (400, 100, 600, 400)


def test_changes_between_two_measures():
    old = {'blocks': [block(1, 0, 0, 100, 50), {**block(2, 0, 100, 100, 50), 'signature': 'img a.png'}],
           'analysis': {'collisions': [{'a': 1, 'b': 2, 'x0': 0, 'y0': 40, 'x1': 100, 'y1': 50, 'area': 1000}],
                        'lint': []}}
    new = {'blocks': [block(1, 0, 0, 100, 50), {**block(2, 0, 120, 100, 80), 'signature': 'img a.png'},
                      {**block(3, 0, 300, 10, 10), 'signature': 'p "new"'}],
           'analysis': {'collisions': [], 'lint': []}}
    lines = layout_report.layout_changes(old, new)
    assert lines[0].startswith('- solved: COLLISION #1 × #2')
    assert lines[1].startswith('- #2 moved by (+0, +20) px, 100×50 -> 100×80 px')
    assert lines[2].startswith('- new block #3')
    assert layout_report.layout_changes(new, new) == []
