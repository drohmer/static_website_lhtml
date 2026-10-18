"""Tests of the layout analysis (lhtml_site/layout/), on synthetic measurements:
no browser needed."""

import pytest

from lhtml_site.layout import analysis as checks, findings as records, measure, report as markdown_report
from lhtml_site.layout_options import jobs

AREA = {'x': 0, 'y': 0, 'w': 1000, 'h': 500}


def block(id, x, y, w, h, kind='div', position='static', **extra):
    rect = {'x': x, 'y': y, 'w': w, 'h': h}
    return {'id': id, 'kind': kind, 'signature': f'div #{id}', 'box': rect, 'visual': rect,
            'position': position, 'margin': [0, 0, 0, 0], 'font_size': 20,
            'overflow': 'visible', 'scroll': None, 'media': [], **extra}


def find_collisions(blocks, threshold=4):
    """Pairs of blocks whose drawn content overlaps."""
    return checks.find_overlaps(blocks, threshold)[0]


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
    analysis = checks.analyse(layout)
    assert analysis['collisions'] == []
    assert analysis['background_overlaps'] == [{'image': 1, 'other': 2, 'src': 'tri.png'}]
    md = markdown_report.page_markdown('p', 'src/p/index.html.j2', layout)
    assert 'BACKGROUND OVERLAP #2 over #1: only the background' in md


def test_out_of_area_sides():
    out = checks.find_out_of_area([block(1, -20, 480, 1100, 40)], AREA)
    assert out == [{'id': 1, 'left': 20, 'right': 80, 'bottom': 20}]


def test_scrolling_page_bottom_not_checked():
    out = checks.find_out_of_area([block(1, -20, 480, 100, 900)], AREA, scrolling=True)
    assert out == [{'id': 1, 'left': 20}]


def test_clipped_content_only_when_overflow_hidden():
    scroll = {'w': 100, 'h': 300, 'client_w': 100, 'client_h': 200}
    visible = block(1, 0, 0, 100, 200, scroll=scroll)
    hidden = block(2, 0, 0, 100, 200, scroll=scroll)
    hidden['overflow'] = 'hidden'
    assert checks.find_clipped([visible, hidden]) == [{'id': 2, 'w': 0, 'h': 100}]


def test_upscaled_image():
    media = [{'src': 'a.png', 'w': 400, 'h': 200, 'natural_w': 200, 'natural_h': 100},
             {'src': 'b.png', 'w': 100, 'h': 100, 'natural_w': 200, 'natural_h': 200},
             {'src': 'c.png', 'w': 220, 'h': 100, 'natural_w': 200, 'natural_h': 100},   # ×1.1: not visible
             {'src': 'd.svg', 'w': 800, 'h': 400, 'natural_w': 200, 'natural_h': 100, 'vector': True}]
    assert checks.find_upscaled_images([block(1, 0, 0, 400, 200, media=media)]) == \
        [{'id': 1, 'src': 'a.png', 'scale': 2.0}]


def test_vertical_gaps_ignore_positioned_blocks():
    blocks = [block(1, 0, 0, 100, 50), block(2, 0, 400, 100, 50, position='fixed'), block(3, 0, 80, 100, 20)]
    assert checks.vertical_gaps(blocks) == [(1, 3, 30)]


def test_spacers_are_ignored_by_the_analysis():
    layout = {'area': AREA, 'blocks': [block(1, 0, 0, 100, 100), block(2, 0, 0, 1000, 600, kind='spacer')]}
    analysis = checks.analyse(layout)
    assert analysis['collisions'] == [] and analysis['out_of_area'] == []


def test_occupancy():
    layout = {'area': AREA, 'blocks': [block(1, 0, 0, 500, 500)]}
    assert checks.analyse(layout)['occupancy'] == 0.5


def test_cells_of_the_grid():
    """A cell counts when its centre is inside the area (also for a size that is not a multiple of 10)."""
    for w, cells in ((1920, 192), (106, 11), (104, 10), (5, 0)):
        assert len(checks.coverage([], {'x': 0, 'y': 0, 'w': w, 'h': 20})[0]) == cells
    area = {'x': 0, 'y': 0, 'w': 108, 'h': 108}
    assert checks.occupancy([block(1, 0, 0, 108, 108)], area) == 1.0


def test_markdown_report_and_summary():
    layout = {'area': AREA, 'blocks': [block(1, 0, 0, 100, 100), block(2, 50, 50, 100, 100, position='fixed')]}
    checks.analyse(layout)
    md = markdown_report.page_markdown('content/a', 'src/content/a/index.html.j2', layout)
    assert '| 2 | - | div | 50, 50 | 100 × 100 |' in md
    assert 'COLLISION #1 × #2' in md
    summary = markdown_report.summary_markdown([('content/a', 'content/a/layout.md', layout['analysis'])])
    assert '| content/a | 1 | 0 | 1 | 0 | 0 | 0 | 0 |' in summary


def text(x, y, w, h):
    return {'x': x, 'y': y, 'w': w, 'h': h, 't': 'text'}


def test_text_on_background_of_another_block_is_not_a_collision():
    code = block(1, 0, 0, 800, 300, kind='code', ink=[{'x': 0, 'y': 0, 'w': 800, 'h': 300, 't': 'paint'},
                                                      text(10, 10, 300, 30)])
    note = block(2, 400, 10, 300, 40, position='fixed', ink=[text(400, 10, 300, 40)])
    collisions, tight, intentional = checks.find_overlaps([code, note])
    assert collisions == tight == intentional == []


def test_shallow_text_overlap_is_tight():
    title = block(1, 0, 0, 500, 50, kind='title', ink=[text(0, 0, 500, 50)], font_size=40)
    formula = block(2, 0, 42, 500, 60, ink=[text(0, 42, 500, 60)], font_size=35)
    collisions, tight, _ = checks.find_overlaps([title, formula])
    assert collisions == [] and [(t['a'], t['b']) for t in tight] == [(1, 2)]
    deep = block(3, 0, 10, 500, 60, ink=[text(0, 10, 500, 60)], font_size=35)
    collisions, tight, _ = checks.find_overlaps([title, deep])
    assert [(c['a'], c['b']) for c in collisions] == [(1, 3)] and tight == []


def test_intentional_overlay():
    image = block(1, 0, 0, 600, 300, kind='image', ink=[{'x': 0, 'y': 0, 'w': 600, 'h': 300, 't': 'media'}])
    zoom = block(2, 400, 200, 200, 200, kind='image', position='fixed', intentional=True,
                 ink=[{'x': 400, 'y': 200, 'w': 200, 'h': 200, 't': 'media'}])
    layout = {'area': AREA, 'blocks': [image, zoom]}
    analysis = checks.analyse(layout)
    assert analysis['collisions'] == [] and [(c['a'], c['b']) for c in analysis['intentional']] == [(1, 2)]
    assert records.count_problems(analysis) == 0
    assert 'marked as intentional' in markdown_report.page_markdown('p', 's', layout)


def test_hidden_text_is_a_problem():
    sentence = block(1, 0, 0, 900, 40, ink=[text(0, 0, 900, 40)],
                     hidden_text=[{'by': 2, 'x': 600, 'y': 0, 'w': 300, 'h': 40, 'samples': 15, 'total': 50}])
    image = block(2, 600, 0, 300, 100, kind='image', position='fixed',
                  ink=[{'x': 650, 'y': 0, 'w': 100, 'h': 100, 't': 'media'}])
    layout = {'area': AREA, 'blocks': [sentence, image]}
    analysis = checks.analyse(layout)
    assert analysis['hidden_text'] == [{'id': 1, 'by': 2, 'x0': 600, 'y0': 0, 'x1': 900, 'y1': 40, 'fraction': 0.3}]
    md = markdown_report.page_markdown('p', 's', layout)
    assert 'HIDDEN TEXT #1 under #2' in md and '30 % of the text of #1' in md
    # the overlap of the text with the image content is not reported again as a collision
    assert analysis['collisions'] == []


def paint(x, y, w, h):
    return {'x': x, 'y': y, 'w': w, 'h': h, 't': 'paint'}


def test_near_alignment_of_frames_and_text_left_edges():
    # two framed boxes stacked: right edges 6 px apart
    code = block(1, 100, 100, 700, 200, ink=[paint(100, 100, 700, 200)])
    image = block(2, 100, 350, 694, 300, ink=[paint(100, 350, 694, 300)])
    near = checks.find_near_alignments([code, image], AREA)
    assert near == [{'id': 1, 'axis': 'x', 'edge': 'right', 'value': 800, 'ref': 794,
                     'ref_label': 'right of #2', 'delta': 6}]
    # left-aligned text 7 px off a column of the deck
    para = block(3, 159, 700, 400, 40, ink=[text(159, 700, 400, 40)])
    near = checks.find_near_alignments([para], {'x': 0, 'y': 0, 'w': 1000, 'h': 1000}, grid=[152])
    assert [(n['id'], n['edge'], n['ref_label'], n['delta']) for n in near] == [(3, 'left', 'deck column', 7)]


def test_a_block_laid_over_the_page_is_not_in_the_grid_of_the_content():
    # a timer and a page number sit against the page, not in the column grid
    para = block(1, 100, 100, 700, 200, ink=[paint(100, 100, 700, 200)])
    timer = block(2, 100, 350, 694, 300, ink=[paint(100, 350, 694, 300)], intentional=True)
    number = block(3, 100, 700, 694, 40, ink=[paint(100, 700, 694, 40)], position='fixed')
    assert checks.find_near_alignments([para, timer, number], AREA) == []
    # the same block placed in the content is still compared
    assert [n['id'] for n in checks.find_near_alignments([para, dict(timer, intentional=False)], AREA)] == [1]


def test_ragged_text_edges_and_line_boxes_are_not_compared():
    # right end of left-aligned text, left end of centered text, top of line boxes
    a = block(1, 100, 100, 400, 40, ink=[text(100, 100, 400, 40)])
    b = block(2, 100, 200, 405, 40, ink=[text(100, 200, 405, 40)])
    centered = block(3, 306, 300, 200, 40, ink=[text(306, 300, 200, 40)], text_align='center')
    framed = block(4, 300, 400, 210, 100, ink=[paint(300, 400, 210, 100)])
    side = block(5, 700, 105, 200, 40, ink=[text(700, 105, 200, 40)])
    assert checks.find_near_alignments([a, b, centered, framed, side], AREA) == []


def test_image_with_transparent_margin_has_no_precise_edges():
    media = [{'src': 'tri.png', 'box': {'x': 500, 'y': 100, 'w': 300, 'h': 300},
              'content': {'x': 550, 'y': 150, 'w': 200, 'h': 200}}]
    image = block(1, 550, 150, 200, 200, kind='image', media=media,
                  ink=[{'x': 550, 'y': 150, 'w': 200, 'h': 200, 't': 'media'}])
    assert checks._precise_edges(image) == {}
    media[0]['content'] = media[0]['box']
    assert set(checks._precise_edges(image)) == {'left', 'right', 'center', 'top', 'bottom', 'middle'}


def page(title_y=58, title_font=70, body_font=35, words=30, extra=()):
    title = block(1, 62, title_y, 600, 70, kind='title', font_size=title_font, ink=[text(62, title_y, 600, 70)])
    title['signature'] = 'h1 "Title"'
    body = block(2, 112, title_y + 100, 800, 200, kind='list', font_size=body_font,
                 ink=[text(112, title_y + 100, 800, 200)], text={'words': words, 'min_font': body_font})
    return {'area': {'x': 32, 'y': 32, 'w': 1856, 'h': 1016}, 'blocks': [title, body, *extra]}


def test_deck_norms_and_deviations():
    deck = [page() for _ in range(5)] + [page(title_y=80), page(body_font=22)]
    norms = checks.deck_norms(deck)
    assert norms['titles'] == [{'tag': 'h1', 'font': 70, 'pages': 7, 'x_anchor': 'left', 'x': 62,
                                'y_anchor': 'top', 'y': 58}]
    assert norms['columns'] == [62, 112] and norms['body_font'] == 35 and norms['text_fonts'] == [35]
    assert norms['title_gap'] == 30 and norms['words'] == 30
    assert checks.analyse(deck[0], norms=norms)['deviations'] == []
    deviations = checks.analyse(deck[5], norms=norms)['deviations']
    assert deviations == [{'kind': 'title_position', 'id': 1, 'value': [62, 80], 'norm': [62, 58],
                           'anchor': ['left', 'top']}]
    deviations = checks.analyse(deck[6], norms=norms)['deviations']
    assert deviations == [{'kind': 'text_font', 'id': 2, 'value': 22, 'norm': [35]}]
    assert 'TEXT FONT #2: text at 22 px' in markdown_report.page_markdown('p', 's', deck[6])
    assert 'page title `h1` 70 px (7 pages): left x 62, top y 58' in markdown_report.norms_markdown(norms)


def test_centered_titles_of_various_lengths():
    deck = []
    for w in (400, 600, 800):
        t = block(1, 960 - w // 2, 500, w, 90, kind='title', font_size=91, ink=[text(960 - w // 2, 500, w, 90)])
        t['signature'] = 'h1 "Section"'
        deck.append({'area': AREA, 'blocks': [t]})
    norms = checks.deck_norms(deck)
    assert [(t['x_anchor'], t['x']) for t in norms['titles']] == [('center', 960)]


def test_density_and_warnings():
    blocks = [block(1, 0, 0, 500, 100, ink=[text(0, 0, 500, 50), text(0, 50, 300, 50)],
                    text={'words': 70, 'formulas': 2, 'code_lines': 0, 'items': 3, 'min_font': 35}),
              block(2, 0, 200, 500, 200, kind='code', ink=[paint(0, 200, 500, 200), text(10, 210, 300, 20)],
                    text={'words': 0, 'formulas': 0, 'code_lines': 8, 'items': 0, 'min_font': 17})]
    d = checks.density(blocks, AREA)
    assert (d['words'], d['formulas'], d['code_lines'], d['items'], d['text_lines'], d['min_font']) == \
        (70, 2, 8, 3, 2, 17)
    assert checks.find_density_warnings(d, max_words=60, min_font=20) == [
        {'kind': 'words', 'value': 70, 'limit': 60}, {'kind': 'min_font', 'value': 17, 'limit': 20}]
    layout = {'area': AREA, 'blocks': blocks}
    analysis = checks.analyse(layout, limits={'max_words': 60, 'min_font': 20})
    assert records.count_warnings(analysis) == 2
    md = markdown_report.page_markdown('p', 's', layout)
    assert 'DENSE: 70 words' in md and 'SMALL FONT: 17 px' in md and '## Density' in md


def test_contact_sheets():
    analysis = checks.analyse({'area': AREA, 'blocks': [block(1, 0, 0, 100, 100),
                                                                block(2, 50, 50, 100, 100)]})
    rows = [(f'p{i}', f'dir/p{i}', analysis) for i in range(20)]
    sheets = markdown_report.contact_sheets_html(rows, {'w': 1920, 'h': 1080}, columns=4, rows_per_sheet=4)
    assert len(sheets) == 2 and sheets[0].count('<figure>') == 16 and sheets[1].count('<figure>') == 4
    assert '<img src="dir/p16/render.png"><figcaption><b>17</b> p16 <span class="p">P1</span>' in sheets[1]


def test_deck_without_page_titles():
    deck = [{'area': AREA, 'blocks': [block(1, 10, 10, 300, 40, ink=[text(10, 10, 300, 40)],
                                            text={'words': 5, 'min_font': 20})]} for _ in range(4)]
    norms = checks.deck_norms(deck)
    assert norms['titles'] == [] and norms['columns'] == [10]
    assert checks.analyse(deck[0], norms=norms)['deviations'] == []


def test_no_density_warnings_on_scrolling_pages():
    blocks = [block(1, 0, 0, 500, 2000, ink=[text(0, 0, 500, 2000)], text={'words': 900, 'min_font': 14})]
    analysis = checks.analyse({'area': AREA, 'blocks': blocks, 'scrolling': True})
    assert analysis['dense'] == [] and analysis['density']['words'] == 900


def test_a_scrolling_page_is_measured_over_its_content_not_over_one_window():
    """AREA is the window (1000x500); the page is four windows long. Measured
    over the window, the text would cover 200 % of the page and the space
    left under the last block would be a negative number stated as a fact."""
    blocks = [block(1, 0, 0, 1000, 2000, ink=[text(0, 0, 1000, 1000)], text={'words': 300})]
    analysis = checks.analyse({'area': AREA, 'blocks': blocks, 'scrolling': True})
    assert analysis['free_bottom'] is None               # a page continues: the question has no answer
    assert analysis['occupancy'] == 0.5                  # half of the 2000 px of content, not 200 %
    assert analysis['density']['text_area'] == 0.5
    markdown = markdown_report.page_markdown('p', 's', {'area': AREA, 'blocks': blocks,
                                                        'analysis': analysis})
    assert analysis['measured_height'] == 2000           # the content, not the window
    assert 'measured over its content, y 0..2000' in markdown
    assert 'free space at the bottom' not in markdown

    # a slide keeps both: it is one window, and what is left under it is a fact
    slide = checks.analyse({'area': AREA, 'blocks': [block(1, 0, 0, 1000, 250)]})
    assert slide['free_bottom'] == 250


def test_short_wrapped_fits_on_one_line_of_the_slide():
    area = {'x': 100, 'y': 0, 'w': 1700, 'h': 900}
    item = lambda text, natural, x=150, **w: dict({'tag': 'li', 'text': text, 'lines': 2, 'first_w': 400,
                                                  'last_w': 300, 'natural_w': natural, 'avail_w': 420, 'x': x}, **w)
    b = block(1, 0, 0, 500, 100, wrapped=[
        item('Fits on the slide', 710),                      # 710 px <= 1800 - 150
        item('Too long for the slide', 1700),                 # wraps anyway
        item('Starts far right', 710, x=1200),                # 710 px > 1800 - 1200
        item('Orphan word', 470, last_w=60),                  # already a WRAPPED item
        item('Broken in the source', 400),                    # <br>: no width missing
        {'tag': 'h2', 'text': 'Title', 'lines': 2, 'first_w': 400, 'last_w': 300,
         'natural_w': 710, 'avail_w': 420, 'x': 150},         # titles: WRAPPED
        {'tag': 'li', 'text': 'Old report', 'lines': 2, 'first_w': 400, 'last_w': 300}])
    found = checks.find_short_wrapped([b], area)
    assert [(w['text'], w['missing']) for w in found] == [('Fits on the slide', 290)]
    assert records._line_item('p') == 'paragraph' and records._line_item('div.ref') == 'reference'


def test_text_over_the_navigation_counts_and_a_figure_under_it_does_not():
    """The navigation is drawn over the content: a figure passing under it is
    what a full-bleed slide is for, a text written there is unreadable."""
    nav = [{'x': 880, 'y': 440, 'w': 120, 'h': 60, 'name': 'nav'}]
    text = block(1, 900, 450, 80, 40, ink=[{'x': 900, 'y': 450, 'w': 80, 'h': 40, 't': 'text'}])
    figure = block(2, 880, 440, 200, 200, kind='image',
                   ink=[{'x': 880, 'y': 440, 'w': 200, 'h': 200, 't': 'media'}])
    elsewhere = block(3, 0, 0, 100, 100, ink=[{'x': 0, 'y': 0, 'w': 100, 'h': 100, 't': 'text'}])
    found = checks.find_reserved_overlaps([text, figure, elsewhere], nav)
    assert [(f['id'], f['name']) for f in found] == [(1, 'nav')]


def test_wrapped_titles_and_items():
    b = block(1, 0, 0, 500, 100, wrapped=[
        {'tag': 'h2', 'text': 'A long title', 'lines': 2, 'first_w': 500, 'last_w': 400},
        {'tag': 'li', 'text': 'An item', 'lines': 2, 'first_w': 800, 'last_w': 100},
        {'tag': 'li', 'text': 'A paragraph item', 'lines': 2, 'first_w': 800, 'last_w': 600},
        {'tag': 'li', 'text': 'A long item', 'lines': 3, 'first_w': 800, 'last_w': 100}])
    assert [w['text'] for w in checks.find_wrapped([b])] == ['A long title', 'An item']


def test_row_of_figures_not_aligned():
    rows = [{'figures': ['a.png', 'b.png', 'c.png'], 'tops': [363, 363, 377], 'bottoms': [500, 500, 500]},
            {'figures': ['d.png', 'e.png'], 'tops': [100, 101], 'bottoms': [200, 300]}]     # 100 px: deliberate
    found = checks.find_row_misalignments([block(1, 0, 0, 10, 10, rows=rows)])
    assert [(f['edge'], f['spread']) for f in found] == [('top', 14)]


def test_figure_small_in_its_box_or_cropped():
    media = [{'src': 'a.png', 'box': {'x': 0, 'y': 0, 'w': 400, 'h': 400}, 'drawn': {'w': 400, 'h': 100, 'fit': 'contain'}},
             {'src': 'b.png', 'box': {'x': 0, 'y': 0, 'w': 400, 'h': 400}, 'drawn': {'w': 600, 'h': 400, 'fit': 'cover'}},
             {'src': 'c.png', 'box': {'x': 0, 'y': 0, 'w': 400, 'h': 400}, 'drawn': {'w': 400, 'h': 380, 'fit': 'contain'}}]
    found = checks.find_fit([block(1, 0, 0, 400, 400, media=media)])
    assert [(f['src'], f['kind'], f['sides']) for f in found] == [('a.png', 'small', 'top and bottom'),
                                                                  ('b.png', 'cropped', 'left and right')]


def test_largest_free_rect():
    blocks = [block(1, 0, 0, 1000, 100), block(2, 0, 100, 400, 400)]
    free = checks.largest_free_rect(blocks, AREA)
    assert (free['x'], free['y'], free['w'], free['h']) == (400, 100, 600, 400)


def test_changes_between_two_measures():
    old = {'blocks': [block(1, 0, 0, 100, 50), {**block(2, 0, 100, 100, 50), 'signature': 'img a.png'}],
           'analysis': {'collisions': [{'a': 1, 'b': 2, 'x0': 0, 'y0': 40, 'x1': 100, 'y1': 50, 'area': 1000}],
                        'lint': []}}
    new = {'blocks': [block(1, 0, 0, 100, 50), {**block(2, 0, 120, 100, 80), 'signature': 'img a.png'},
                      {**block(3, 0, 300, 10, 10), 'signature': 'p "new"'}],
           'analysis': {'collisions': [], 'lint': []}}
    lines = markdown_report.layout_changes(old, new)
    assert lines[0].startswith('- solved: COLLISION #1 × #2')
    assert lines[1].startswith('- #2 moved by (+0, +20) px, 100×50 -> 100×80 px')
    assert lines[2].startswith('- new block #3')
    assert markdown_report.layout_changes(new, new) == []


def test_changes_of_problems_that_repeat():
    """Two identical blocks with the same problem, then one: one problem solved."""
    image = lambda n: {**block(n, 0, 100 * n, 100, 50), 'signature': 'img a.png'}
    upscaled = lambda n: {'id': n, 'src': 'a.png', 'scale': 2}
    old = {'blocks': [image(1), image(2)], 'analysis': {'upscaled_images': [upscaled(1), upscaled(2)], 'lint': []}}
    new = {'blocks': [image(1), image(2)], 'analysis': {'upscaled_images': [upscaled(1)], 'lint': []}}
    assert markdown_report.layout_changes(old, new) == ['- solved: UPSCALED IMAGE #2: a.png displayed at ×2 (blurry)']


def test_collapsed_figure():
    media = [{'src': 'a.png', 'w': 0, 'h': 0, 'natural_w': 200, 'natural_h': 100},
             {'src': 'b.png', 'w': 300, 'h': 3, 'natural_w': 200, 'natural_h': 100},
             {'src': 'c.png', 'w': 200, 'h': 100, 'natural_w': 200, 'natural_h': 100},
             {'src': 'd.mp4', 'w': 0, 'h': 0, 'natural_w': 0, 'natural_h': 0},      # not loaded: no size
             {'src': 'e.png', 'w': 900, 'h': 4, 'natural_w': 1000, 'natural_h': 4}]   # a thin rule, as it is
    found = checks.find_collapsed([block(1, 0, 0, 400, 200, media=media)])
    assert [f['src'] for f in found] == ['a.png', 'b.png']
    assert 'COLLAPSED FIGURE #1: a.png drawn at 0 × 0 px' in '\n'.join(markdown_report.problem_lines({'collapsed': found}))


def test_svg_overflow_and_labels():
    svg = [{'src': 'fig.svg', 'overflow': {'left': 92, 'top': 0, 'right': 2, 'bottom': 0},
            'labels': [{'text': 'translation', 'over': 'line'}]},
           {'src': 'ok.svg', 'overflow': {'left': 0, 'top': 0, 'right': 3, 'bottom': 0}, 'labels': []}]
    blocks = [block(1, 0, 0, 400, 200, svg=svg)]
    overflow = checks.find_svg_overflow(blocks)
    assert overflow == [{'id': 1, 'src': 'fig.svg', 'left': 92, 'top': 0, 'right': 2, 'bottom': 0}]
    assert '(92 px left, 2 px right): cut when shown' in markdown_report.problem_lines({'svg_overflow': overflow})[0]
    assert checks.find_svg_labels(blocks) == [{'id': 1, 'src': 'fig.svg', 'texts': ['translation'],
                                                      'count': 1, 'over': 'line'}]
    many = [block(1, 0, 0, 400, 200, svg=[{'src': 'plot.svg', 'overflow': None,
                                          'labels': [{'text': f'l{k}', 'over': 'line'} for k in range(40)]}])]
    lines = markdown_report.page_markdown('p', 's', {'area': AREA, 'blocks': [], 'analysis': {
        'occupancy': 0, 'free_bottom': 0, 'gaps': [], 'svg_labels': checks.find_svg_labels(many)}})
    assert lines.count('SVG LABEL') == 1 and '"l0", "l1", "l2" and 37 more are drawn across a line' in lines
    analysis = {'svg_overflow': overflow, 'svg_labels': checks.find_svg_labels(blocks)}
    assert records.count_problems(analysis) == 1 and records.count_warnings(analysis) == 1


def test_a_root_that_does_not_match_the_theme_is_reported():
    """Every page measured as a single block means the root selector misses
    the content of the theme: the checks on the blocks then find nothing."""
    warnings = []
    log = type('Log', (), {'warning': lambda self, text: warnings.append(text)})()
    page = {'name': 'a.html'}

    one_block = [(page, 'a/layout.json', {'root': 'body', 'blocks': [{'id': 1}]})]
    measure.warn_degenerate_root(one_block, {'root': 'body'}, log)
    assert len(warnings) == 1
    assert "single block (root: 'body')" in warnings[0] and 'theme.yaml' in warnings[0]

    warnings.clear()                      # a measured page with real blocks: nothing to say
    measure.warn_degenerate_root(
        [(page, 'a/layout.json', {'root': '#main', 'blocks': [{'id': 1}, {'id': 2}]})],
        {'root': '#main'}, log)
    measure.warn_degenerate_root([], {'root': 'body'}, log)
    assert warnings == []


def test_canvas_bounds_are_candidates_not_proof_of_occluded_text():
    canvas = block(1, 0, 0, 800, 400, kind='image', unverified_canvas=True,
                   ink=[{'x': 0, 'y': 0, 'w': 800, 'h': 400, 't': 'media'}])
    label = block(2, 20, 20, 100, 30, ink=[{'x': 20, 'y': 20, 'w': 100, 'h': 30, 't': 'text'}],
                  hidden_text=[{'by': 1, 'x': 20, 'y': 20, 'w': 100, 'h': 30, 'samples': 10, 'total': 10}])
    result = checks.analyse({'blocks': [canvas, label], 'area': AREA})
    assert not result['hidden_text'] and not result['collisions']
    assert result['canvas_overlaps'][0]['kind'] == 'hidden_text'
    assert records.count_problems(result) == 0
    assert records.count_warnings(result) >= 1


def test_jobs_option():
    assert jobs({'jobs': 3}) == 3
    assert 1 <= jobs({'jobs': 'auto'}) <= 6 and jobs({}) >= 1
    for bad in (0, -2, 'four', True, 1.5):
        with pytest.raises(ValueError):
            jobs({'jobs': bad})


def test_a_block_over_a_navigation_of_several_parts_is_reported_once():
    """The theme is measured as one rectangle per part that paints, so a
    navigation of five icons must not turn one full-bleed image into five
    findings."""
    nav = [{'x': 1630 + 40 * k, 'y': 990, 'w': 30, 'h': 40, 'name': 'nav'} for k in range(5)]
    banner = block(1, 0, 0, 1920, 1080,
                   ink=[{'x': 0, 'y': 0, 'w': 1920, 'h': 1080, 't': 'text'}])
    found = checks.find_reserved_overlaps([banner], nav)
    assert len(found) == 1
    assert found[0]['id'] == 1 and found[0]['name'] == 'nav'
    assert (found[0]['x0'], found[0]['x1']) == (1630, 1820)      # over all the parts


def test_an_intentional_overlay_is_measured_against_the_page():
    """A full-bleed figure (class overlay) covers the slide on purpose, so it
    is not out of the usable area; one that spills past the page still is."""
    page = {'viewport': {'w': 1920, 'h': 1080}}
    usable = {'x': 32, 'y': 32, 'w': 1856, 'h': 1016}
    full_bleed = block(1, 0, 0, 1920, 1080, position='fixed', intentional=True)
    in_the_flow = block(2, 0, 0, 1920, 1080)            # placed in the content, not over it
    spilling = block(3, -50, 0, 2020, 1080, position='fixed', intentional=True)

    found = checks.find_out_of_area([full_bleed, in_the_flow, spilling], usable,
                                           page=checks._page_rect(page))
    assert [f['id'] for f in found] == [2, 3]
    assert found[1] == {'id': 3, 'left': 50, 'right': 50}
    # without the size of the page, every block is compared with the usable area
    assert [f['id'] for f in checks.find_out_of_area([full_bleed], usable)] == [1]


def test_a_block_fixed_to_the_viewport_is_measured_against_the_page():
    """A timer, a page number or a watermark is fixed to the viewport: it is
    laid over the page, in the margin the content keeps free, and saying so
    once per slide says nothing. What is still reported: the same block when
    it leaves the page, and a block of the content at the same place."""
    page = {'viewport': {'w': 1920, 'h': 1080}}
    usable = {'x': 32, 'y': 32, 'w': 1856, 'h': 1016}   # content stops at y 1048
    timer = block(1, 40, 1058, 35, 14, position='fixed')
    off_the_page = block(2, 40, 1074, 35, 14, position='fixed')
    in_the_flow = block(3, 40, 1058, 35, 14)

    found = checks.find_out_of_area([timer, off_the_page, in_the_flow], usable,
                                    page=checks._page_rect(page))
    assert [f['id'] for f in found] == [2, 3]
    assert found[0] == {'id': 2, 'bottom': 8}           # past the page itself
    assert found[1] == {'id': 3, 'bottom': 24}          # past the usable area
    # a sticky block stays part of the flow: the usable area applies to it
    sticky = block(4, 40, 1058, 35, 14, position='sticky')
    assert [f['id'] for f in checks.find_out_of_area([sticky], usable,
                                                     page=checks._page_rect(page))] == [4]


def test_a_finding_says_where_its_blocks_are_written():
    """The agent opens the file at the line instead of searching for a
    signature. The line alone when the block is written in the source of
    the page, the file and the line when it comes from another one, and
    said plainly when nothing marks the block (a block a script writes)."""
    page = 'src/a/index.html.j2'
    sources = {'1': (page + ':12', False), '2': ('src/_include/header.j2:4', False),
               '3': (None, False), '4': (page + ':20', True)}
    assert markdown_report.where(page + ':12', page) == 'line 12'
    assert markdown_report.where('src/_include/header.j2:4', page) == 'src/_include/header.j2:4'
    assert markdown_report.where(None, page) == 'no source marker'
    # the line of what is around the block, not of the block
    assert markdown_report.where(page + ':20', page, near=True) == 'near line 20'

    place = lambda analysis: [markdown_report.located(f, sources, page)
                              for f in records.findings(analysis)]
    one = place({'clipped': [{'id': 1, 'w': 10, 'h': 0}]})
    assert one == ['- CLIPPED #1: 10 px (width) / 0 px (height) of content hidden [line 12]']
    two = place({'hidden_text': [{'id': 3, 'by': 2, 'x0': 0, 'y0': 0, 'x1': 9, 'y1': 9, 'fraction': 1}]})
    assert two[0].endswith('[#3 no source marker, #2 src/_include/header.j2:4]')
    # a finding that names no block (a page-wide one) is left alone
    assert place({'dense': [{'kind': 'words', 'value': 90, 'limit': 80}]}) \
        == ['- DENSE: 90 words of text (limit 80)']
    assert place({'clipped': [{'id': 4, 'w': 10, 'h': 0}]})[0].endswith('[near line 20]')


def test_the_report_of_a_page_carries_the_places_of_its_findings():
    page = 'src/a/index.html.j2'
    layout = {'area': AREA, 'scrolling': False,
              'blocks': [block(1, 0, 0, 400, 200, source=page + ':7',
                               media=[{'src': 'a.png', 'w': 400, 'h': 200,
                                       'natural_w': 200, 'natural_h': 100}]),
                         block(2, 0, 300, 400, 100)]}          # written by nobody
    checks.analyse(layout)
    text = markdown_report.page_markdown('a', page, layout)
    assert 'UPSCALED IMAGE #1' in text and '[line 7]' in text
    assert 'Each finding below ends with where its blocks are written' in text

    # the diff of two builds compares the findings without their places: a
    # line that moves is not a problem that changed
    assert all('[' not in line for line in markdown_report.problem_lines(layout['analysis']))



def test_every_check_declares_its_severity_and_the_blocks_it_names():
    """One shape for every finding, and nothing else holds the list of
    checks: a check that is not declared is not reported, counted or diffed."""
    keys = [key for key, _, _ in records.CHECKS]
    assert len(set(keys)) == len(keys)
    assert set(severity for _, severity, _ in records.CHECKS) <= set(records.SEVERITIES)

    layout = {'area': AREA, 'scrolling': False,
              'blocks': [block(1, 0, 0, 400, 200, ink=[text(0, 0, 400, 200)]),
                         block(2, 10, 10, 100, 40, ink=[text(10, 10, 100, 40)])]}
    analysis = checks.analyse(layout)
    found = records.findings(analysis)
    assert found and found is analysis['findings']        # recorded, not recomputed
    for f in found:
        assert set(f) == {'key', 'code', 'severity', 'blocks', 'subject', 'detail', 'text', 'data'}
        assert f['severity'] in records.SEVERITIES
        assert f['text'].startswith(f['code'])
        assert all(isinstance(i, int) for i in f['blocks'])
    assert records.count_problems(analysis) == sum(1 for f in found if f['severity'] == 'problem')


def test_the_diff_of_two_builds_reads_the_codes_not_the_sentences():
    """A wording change must not read as a problem that appeared: the diff
    compares the code of a finding and the signatures of its blocks."""
    def measured(width):
        layout = {'area': AREA, 'scrolling': False,
                  'blocks': [block(1, 0, 0, width, 40, kind='image',
                                   media=[{'src': 'a.png', 'w': width, 'h': 40,
                                           'natural_w': 50, 'natural_h': 20}],
                                   ink=[paint(0, 0, width, 40)])]}
        checks.analyse(layout)
        return layout

    old, new = measured(400), measured(400)
    assert [f['code'] for f in new['analysis']['findings']] == ['UPSCALED IMAGE']
    assert markdown_report.layout_changes(old, new) == []
    # the same problem said differently is still the same problem
    for f in new['analysis']['findings']:
        f['text'] = f['text'].replace('displayed at', 'shown at')
    assert markdown_report.layout_changes(old, new) == []
