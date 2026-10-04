"""Layout report: positions, collisions and overflows of the blocks of each page.

The layout is measured in headless Chrome (assets/layout_measure.js,
requires `npm install`), then analysed here. For each page, the report is
written to <config_dir>/.layout/pages/<relative HTML path>/:

    layout.md    blocks (position, size, signature), detected problems,
                 warnings, differences with the rest of the deck, density
    layout.json  raw measurements and analysis
    render.png   real render
    overlay.png  real render with numbered block outlines
    blocks.png   one solid rectangle per block (content hidden)

<config_dir>/.layout/summary.md lists all pages sorted by number of problems,
with the usual values of the deck (title position, columns, body font size,
...: also in deck.json), and contact_NN.png shows thumbnails of all pages. Coordinates are in CSS pixels, origin at the top-left corner of
the page (1920x1080 for slides).

Options (configure.yaml):
    plugin_arg:
      layout_report:
        root: 'body'         # CSS selector of the content root
                             # (webpage-frame theme: '#main-content-centered')
        exclude: 'nav, footer'   # children of the root that are not content
        width: 1920          # viewport size
        height: 1080
        images: true         # write overlay.png / blocks.png
        threshold: 4         # minimal overlap / overflow (px) reported
        output: '.layout/'   # output directory, relative to the config directory
        max_words: 80        # DENSE above this number of words per slide
        min_font: 20         # SMALL FONT below this font size (px), slides only
        contact_columns: 4   # thumbnails per row / rows per contact sheet
        contact_rows: 4
"""

import json
import os
import shutil
import subprocess
import tempfile

from lib.lint import Linter
from lib.structure import built_pages, structure
from lib.configuration import layout_output_directory


DEFAULTS = {'root': 'body', 'exclude': 'nav, footer', 'width': 1920, 'height': 1080, 'images': True,
            'threshold': 4, 'output': '.layout/', 'max_words': 80, 'min_font': 20,
            'contact_columns': 4, 'contact_rows': 4}

FLOW_POSITIONS = ('static', 'relative', 'sticky')

path_current_file = os.path.dirname(os.path.abspath(__file__)) + '/'


# ---------------------------------------------------------------------------
# Analysis (pure functions on the measured layout)
# ---------------------------------------------------------------------------

def _as_tuple(r, t='paint'):
    return r['x'], r['y'], r['x'] + r['w'], r['y'] + r['h'], r.get('t', t)


def _rect(block):
    """Bounding rectangle of the ink of a block, or its layout box for spacers."""
    return _as_tuple(block.get('visual') or block['box'])[:4]


def _ink(block):
    """Typed ink rectangles (x0, y0, x1, y1, t) of a block, t in text /
    media / paint; its bounding rectangle if the measurement has no detail."""
    rects = block.get('ink')
    return [_as_tuple(r) for r in rects] if rects else [_rect(block) + ('paint',)]


def _overlap(r, s, threshold):
    """Intersection of two rectangles if larger than `threshold` in both
    directions, else None."""
    x0, y0, x1, y1 = max(r[0], s[0]), max(r[1], s[1]), min(r[2], s[2]), min(r[3], s[3])
    return (x0, y0, x1, y1) if x1 - x0 > threshold and y1 - y0 > threshold else None


def _visible(blocks):
    """Blocks that draw something (spacers excluded)."""
    return [b for b in blocks if b.get('kind') != 'spacer']


def _bounds(parts):
    return {'x0': min(p[0] for p in parts), 'y0': min(p[1] for p in parts),
            'x1': max(p[2] for p in parts), 'y1': max(p[3] for p in parts),
            'area': sum((p[2] - p[0]) * (p[3] - p[1]) for p in parts)}


def find_overlaps(blocks, threshold=4, tight_ratio=0.4):
    """Classify the overlaps between the ink of pairs of blocks.

    - text on the background of another block: ignored (whether the text is
      hidden is checked separately, see hidden text);
    - text on text or on an image, by less than tight_ratio × font size
      vertically: 'tight' (the line box of the text, taller than its glyphs,
      overlaps; the glyphs usually do not touch);
    - any other overlap (text on text, text on image content, images,
      backgrounds): 'collision', or 'intentional' if one of the blocks is
      marked as an intentional overlay (class 'overlay').

    Returns (collisions, tight, intentional): lists of dicts
    (a, b, x0, y0, x1, y1, area) with the bounds and area of the overlap.
    """
    collisions, tight, intentional = [], [], []
    for i, a in enumerate(blocks):
        ink_a = _ink(a)
        for b in blocks[i + 1:]:
            hard, soft = [], []
            min_font = min(a.get('font_size') or 16, b.get('font_size') or 16)
            for r in ink_a:
                for s in _ink(b):
                    o = _overlap(r, s, threshold)
                    if not o:
                        continue
                    types = {r[4], s[4]}
                    if types == {'text', 'paint'}:
                        continue
                    if 'text' in types and 'paint' not in types and o[3] - o[1] < tight_ratio * min_font:
                        soft.append(o)
                    else:
                        hard.append(o)
            if hard:
                target = intentional if a.get('intentional') or b.get('intentional') else collisions
                target.append({'a': a['id'], 'b': b['id'], **_bounds(hard)})
            elif soft:
                tight.append({'a': a['id'], 'b': b['id'], **_bounds(soft)})
    return collisions, tight, intentional


def find_collisions(blocks, threshold=4):
    """Pairs of blocks whose drawn content overlaps (see find_overlaps)."""
    return find_overlaps(blocks, threshold)[0]


def find_hidden_text(blocks):
    """Text hidden by another block drawn on top of it (measured in the
    browser): {id, by, x0, y0, x1, y1, fraction} where fraction is the part
    of the samples taken along the lines of text of the block."""
    result = []
    for b in blocks:
        for h in b.get('hidden_text', []):
            result.append({'id': b['id'], 'by': h['by'], 'x0': h['x'], 'y0': h['y'],
                           'x1': h['x'] + h['w'], 'y1': h['y'] + h['h'],
                           'fraction': round(h['samples'] / max(h['total'], 1), 2)})
    return result


def find_background_overlaps(blocks, collisions, threshold=4):
    """Blocks that overlap only the uniform or transparent background of an
    image of another block (not its drawn content): informational, not a
    problem. Returns dicts (image, other, src)."""
    colliding = {frozenset((c['a'], c['b'])) for c in collisions}
    result = []
    for img_block in blocks:
        for m in img_block.get('media', []):
            if not m.get('box') or not m.get('content') or m['box'] == m['content']:
                continue
            box = _as_tuple(m['box'])
            for other in blocks:
                if other is img_block or frozenset((img_block['id'], other['id'])) in colliding:
                    continue
                if any(_overlap(box, r, threshold) for r in _ink(other)):
                    result.append({'image': img_block['id'], 'other': other['id'], 'src': m['src']})
    return result


def find_out_of_area(blocks, area, threshold=4, scrolling=False):
    """Blocks extending beyond the usable area: {id, left, top, right, bottom} in px.
    On a scrolling page (web page, not a slide), the bottom side is not checked."""
    result = []
    ax0, ay0, ax1, ay1 = area['x'], area['y'], area['x'] + area['w'], area['y'] + area['h']
    for b in blocks:
        x0, y0, x1, y1 = _rect(b)
        out = {'left': ax0 - x0, 'top': ay0 - y0, 'right': x1 - ax1, 'bottom': y1 - ay1}
        out = {k: v for k, v in out.items() if v > threshold and not (scrolling and k == 'bottom')}
        if out:
            result.append({'id': b['id'], **out})
    return result


def find_clipped(blocks, threshold=4):
    """Blocks whose content is cut by overflow hidden/clip/scroll: {id, w, h} hidden px."""
    result = []
    for b in blocks:
        s = b.get('scroll')
        if not s or b.get('overflow', 'visible') == 'visible':
            continue
        hidden_w, hidden_h = s['w'] - s['client_w'], s['h'] - s['client_h']
        if hidden_w > threshold or hidden_h > threshold:
            result.append({'id': b['id'], 'w': max(hidden_w, 0), 'h': max(hidden_h, 0)})
    return result


def find_upscaled_images(blocks, tolerance=1.25):
    """Bitmap images displayed noticeably larger than their native size
    (blurry): {id, src, scale}. Vector images (SVG) are never blurry."""
    result = []
    for b in blocks:
        for m in b.get('media', []):
            if m.get('vector') or not m.get('natural_w'):
                continue
            if m['w'] > m['natural_w'] * tolerance:
                result.append({'id': b['id'], 'src': m['src'], 'scale': round(m['w'] / m['natural_w'], 2)})
    return result


def vertical_gaps(blocks):
    """Gaps between consecutive in-flow blocks, top to bottom: [(id_above, id_below, gap px)]."""
    flow = sorted((b for b in blocks if b.get('position') in FLOW_POSITIONS), key=lambda b: _rect(b)[1])
    return [(a['id'], b['id'], _rect(b)[1] - _rect(a)[3]) for a, b in zip(flow, flow[1:])]


def occupancy(blocks, area, step=10):
    """Fraction of the usable area covered by the ink of the blocks (sampled on a grid)."""
    if area['w'] <= 0 or area['h'] <= 0:
        return 0.0
    rects = [r[:4] for b in blocks for r in _ink(b)]
    covered = total = 0
    for y in range(area['y'] + step // 2, area['y'] + area['h'], step):
        for x in range(area['x'] + step // 2, area['x'] + area['w'], step):
            total += 1
            if any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in rects):
                covered += 1
    return covered / total if total else 0.0


# ---------------------------------------------------------------------------
# Alignment, density and consistency with the rest of the deck
# ---------------------------------------------------------------------------

def _align_parts(block):
    """Typed parts (x0, y0, x1, y1, t) used for alignment: ink of text and
    backgrounds, and boxes of images: t = 'media' when the image fills its
    box, 'trimmed' when it has a uniform or transparent margin (its drawn
    shape is then only known to the image cell)."""
    boxes = [_as_tuple(m['box'])[:4] + ('media' if not m.get('content') or m['content'] == m['box'] else 'trimmed',)
             for m in block.get('media', []) if m.get('box')]
    inside = lambda r: any(b[0] <= r[0] and b[1] <= r[1] and r[2] <= b[2] and r[3] <= b[3] for b in boxes)
    return [r for r in _ink(block) if r[4] != 'media' or not inside(r)] + boxes


def _align_rect(block):
    parts = _align_parts(block)
    return tuple(f(p[i] for p in parts) for i, f in enumerate((min, min, max, max)))


def _precise_edges(block):
    """Edges of a block whose position is meaningful for alignment, i.e.
    those drawn by an image filling its box or by a background/border, and
    for text, the side it is aligned on (left, right, or center). The top
    and bottom of the line box of text do not show where the eye sees the
    text; neither does the box of an image with a transparent margin.
    Center and middle need both sides."""
    parts = _align_parts(block)
    x0, y0, x1, y1 = _align_rect(block)
    at = lambda i, v: {p[4] for p in parts if p[i] == v}
    rigid = lambda i, v: bool(at(i, v) & {'media', 'paint'})
    align = block.get('text_align', 'start')
    text_side = {'right': 'right', 'end': 'right', 'center': 'center', '-webkit-center': 'center'}.get(align, 'left')
    edges = {}
    left, right = rigid(0, x0), rigid(2, x1)
    if left or (text_side == 'left' and 'text' in at(0, x0)):
        edges['left'] = x0
    if right or (text_side == 'right' and 'text' in at(2, x1)):
        edges['right'] = x1
    if (left and right) or (text_side == 'center' and 'text' in at(0, x0) | at(2, x1)):
        edges['center'] = (x0 + x1) // 2
    if rigid(1, y0):
        edges['top'] = y0
    if rigid(3, y1):
        edges['bottom'] = y1
    if 'top' in edges and 'bottom' in edges:
        edges['middle'] = (y0 + y1) // 2
    return edges


def _tag(block):
    return block['signature'].split(' ')[0].split('.')[0].split('[')[0]


def page_title(blocks):
    """The title of a page: its first block, if it is a heading."""
    return blocks[0] if blocks and blocks[0]['kind'] == 'title' else None


def find_near_alignments(blocks, area, grid=(), aligned=2, near=12):
    """Blocks almost, but not exactly, aligned with something. Only precise
    edges are compared (see _precise_edges): left edges with the left edges
    of the other blocks, of the usable area and of the columns of the deck
    (grid); right edges and centers with those of the other blocks and of
    the area; tops, bottoms and middles with those of the blocks side by
    side. An edge aligned (within `aligned` px) with a reference is fine, and
    so is a whole axis when the block is centered on a reference (blocks of
    different sizes centered together). Otherwise, the closest reference
    within `near` px of an edge is reported, once per pair of blocks and
    axis: {id, axis, edge, value, ref, ref_label, delta}."""
    edges = {b['id']: _precise_edges(b) for b in blocks}
    rects = {b['id']: _align_rect(b) for b in blocks}
    area_refs = {'left': [(area['x'], 'area left')] + [(g, 'deck column') for g in grid],
                 'right': [(area['x'] + area['w'], 'area right')],
                 'center': [(area['x'] + area['w'] // 2, 'area center')]}
    result, reported = [], set()
    for b in blocks:
        x0, y0, x1, y1 = rects[b['id']]
        others = [o['id'] for o in blocks if o is not b]
        side = {i for i in others if min(y1, rects[i][3]) - max(y0, rects[i][1]) > 0
                and (rects[i][0] >= x1 or rects[i][2] <= x0)}
        for axis, names in (('x', ('left', 'right', 'center')), ('y', ('top', 'bottom', 'middle'))):
            best, centered, side_aligned = None, False, False
            for edge in names:     # sides first, then center: a block aligned
                # by one side has its center off by half the difference of widths
                if edge not in edges[b['id']] or (side_aligned and edge in ('center', 'middle')):
                    continue
                value = edges[b['id']][edge]
                refs = [(edges[i][edge], f'{edge} of #{i}', i) for i in others if edge in edges[i]
                        and (axis == 'x' or i in side)]
                refs += [(v, label, None) for v, label in area_refs.get(edge, [])]
                if any(abs(value - ref) <= aligned for ref, _, _ in refs):
                    centered = centered or edge in ('center', 'middle')
                    side_aligned = side_aligned or edge not in ('center', 'middle')
                    continue
                for ref, label, other in refs:
                    d = abs(value - ref)
                    if d <= near and (best is None or d < abs(best['delta'])):
                        best = {'id': b['id'], 'axis': axis, 'edge': edge, 'value': value, 'ref': ref,
                                'ref_label': label, 'delta': value - ref, 'other': other}
            if best and not centered:
                pair = (axis, frozenset((b['id'], best['other'])))
                if best['other'] is None or pair not in reported:
                    reported.add(pair)
                    result.append({k: v for k, v in best.items() if k != 'other'})
    return result


def density(blocks, area):
    """Amount of content of a page: prose words, formulas, lines of code,
    list items, lines of text, smallest font size, and the fractions of the
    usable area covered by text and by media ink."""
    stats = [b.get('text') or {} for b in blocks]
    fonts = [s['min_font'] for s in stats if s.get('min_font')]
    surface = max(area['w'] * area['h'], 1)
    ink = [r for b in blocks for r in _ink(b)]
    covered = lambda t: sum((r[2] - r[0]) * (r[3] - r[1]) for r in ink if r[4] == t)
    return {'words': sum(s.get('words', 0) for s in stats),
            'formulas': sum(s.get('formulas', 0) for s in stats),
            'code_lines': sum(s.get('code_lines', 0) for s in stats),
            'items': sum(s.get('items', 0) for s in stats),
            'text_lines': sum(1 for b in blocks if b['kind'] != 'code' for r in _ink(b) if r[4] == 'text'),
            'min_font': min(fonts) if fonts else None,
            'text_area': round(covered('text') / surface, 2),
            'media_area': round(covered('media') / surface, 2)}


def find_density_warnings(dens, max_words=80, min_font=20):
    """Pages with too much text or too small text: [{kind, value, limit}]."""
    result = []
    if dens['words'] > max_words:
        result.append({'kind': 'words', 'value': dens['words'], 'limit': max_words})
    if dens['min_font'] is not None and dens['min_font'] < min_font:
        result.append({'kind': 'min_font', 'value': dens['min_font'], 'limit': min_font})
    return result


def _median(values):
    values = sorted(values)
    if not values:
        return None
    n = len(values)
    return values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2


def _title_gap(blocks):
    """Gap between the title of a page and the next in-flow block below it."""
    title = page_title(blocks)
    if not title:
        return None
    below = [_align_rect(b)[1] for b in blocks[1:] if b.get('position') in FLOW_POSITIONS
             and _align_rect(b)[1] >= _align_rect(title)[3]]
    return min(below) - _align_rect(title)[3] if below else None


def _anchor(values):
    """Usual value of a coordinate measured on several pages, as (anchor,
    median): the anchor ('start' or 'center') whose values vary least, e.g.
    'center' for centered titles of various lengths."""
    best = None
    for name, vs in values.items():
        med = _median(vs)
        spread = _median([abs(v - med) for v in vs])
        if best is None or spread < best[2]:
            best = (name, med, spread)
    return best[0], best[1]


def _title_variant(title):
    return {'tag': _tag(title), 'font': title['font_size']}


def deck_norms(layouts, min_share=0.25, min_pages=3):
    """Usual values of a deck (its style), from the measured layouts of all
    its pages:
    - titles: variants of page title (heading tag and font size) used by at
      least min_pages pages, with their usual position (left edge or
      center, top or middle: whichever varies least);
    - columns: x of left edges of in-flow blocks shared by at least
      min_share of the pages (and min_pages);
    - body_font: font size covering the most surface of text;
      text_fonts: font sizes of text used on at least min_pages pages;
    - title_gap: gap below the page title; words per page; occupancy."""
    pages = [_visible(l['blocks']) for l in layouts]
    n = len(pages)
    norms = {'pages': n, 'titles': [], 'columns': [], 'body_font': None, 'text_fonts': [],
             'title_gap': None, 'words': None, 'occupancy': None}
    if n < min_pages:
        return norms

    variants = {}
    for blocks in pages:
        t = page_title(blocks)
        if t:
            variants.setdefault((_tag(t), t['font_size']), []).append(_align_rect(t))
    for (tag, font), rects in sorted(variants.items(), key=lambda kv: -len(kv[1])):
        if len(rects) < min_pages:
            continue
        ax, x = _anchor({'left': [r[0] for r in rects], 'center': [(r[0] + r[2]) // 2 for r in rects]})
        ay, y = _anchor({'top': [r[1] for r in rects], 'middle': [(r[1] + r[3]) // 2 for r in rects]})
        norms['titles'].append({'tag': tag, 'font': font, 'pages': len(rects), 'x_anchor': ax, 'x': x,
                                'y_anchor': ay, 'y': y})

    lefts = [{_align_rect(b)[0] for b in blocks if b.get('position') in FLOW_POSITIONS} for blocks in pages]
    candidates = {x for edges in lefts for x in edges}
    support = {x: sum(1 for edges in lefts if any(abs(x - e) <= 1 for e in edges)) for x in candidates}
    columns = []
    for x, count in sorted(support.items(), key=lambda kv: (-kv[1], kv[0])):
        if count >= max(min_pages, min_share * n) and all(abs(x - c) > 2 for c in columns):
            columns.append(x)
    norms['columns'] = sorted(columns)

    surface, font_pages = {}, {}
    for blocks in pages:
        sizes = set()
        for b in blocks:
            if b['kind'] in ('title', 'code') or not (b.get('text') or {}).get('words'):
                continue
            area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in _ink(b) if r[4] == 'text')
            surface[b['font_size']] = surface.get(b['font_size'], 0) + area
            sizes.add(b['font_size'])
        for size in sizes:
            font_pages[size] = font_pages.get(size, 0) + 1
    if surface:
        norms['body_font'] = max(surface, key=surface.get)
    norms['text_fonts'] = sorted(f for f, c in font_pages.items() if c >= min_pages)
    norms['title_gap'] = _median([g for g in map(_title_gap, pages) if g is not None])
    norms['words'] = _median([sum((b.get('text') or {}).get('words', 0) for b in blocks) for blocks in pages])
    norms['occupancy'] = round(_median([occupancy(blocks, l['area']) for blocks, l in zip(pages, layouts)]), 2)
    return norms


def find_deviations(blocks, norms, tolerance=4):
    """Differences between a page and the usual values of its deck:
    [{kind, id, value, norm}] with kind in
    - title_position: page title of a usual variant, at another position;
    - title_variant: page title of a variant (tag, font size) unusual in the deck;
    - title_gap: unusual gap below the title (usual variant only);
    - text_font: text in a font size unusual in the deck."""
    result = []
    title = page_title(blocks)
    variant = None
    if title and norms.get('titles'):
        variant = next((v for v in norms['titles'] if (v['tag'], v['font']) == (_tag(title), title['font_size'])),
                       None)
        if variant is None:
            result.append({'kind': 'title_variant', 'id': title['id'],
                           'value': f"{_tag(title)} {title['font_size']} px",
                           'norm': ', '.join(f"{v['tag']} {v['font']} px" for v in norms['titles'])})
        else:
            x0, y0, x1, y1 = _align_rect(title)
            x = x0 if variant['x_anchor'] == 'left' else (x0 + x1) // 2
            y = y0 if variant['y_anchor'] == 'top' else (y0 + y1) // 2
            if abs(x - variant['x']) > tolerance or abs(y - variant['y']) > tolerance:
                result.append({'kind': 'title_position', 'id': title['id'], 'value': [x, y],
                               'norm': [variant['x'], variant['y']],
                               'anchor': [variant['x_anchor'], variant['y_anchor']]})
    gap, norm_gap = _title_gap(blocks), norms.get('title_gap')
    main_variant = norms['titles'][0] if norms.get('titles') else None
    if variant is not None and variant is main_variant and gap is not None and norm_gap is not None \
            and abs(gap - norm_gap) > max(12, 0.3 * norm_gap):
        result.append({'kind': 'title_gap', 'id': title['id'], 'value': gap, 'norm': norm_gap})
    fonts = norms.get('text_fonts') or []
    if fonts:
        for b in blocks:
            if b['kind'] not in ('title', 'code') and (b.get('text') or {}).get('words') \
                    and all(abs(b['font_size'] - f) > 1 for f in fonts):
                result.append({'kind': 'text_font', 'id': b['id'], 'value': b['font_size'], 'norm': fonts})
    return result


def analyse(layout, threshold=4, norms=None, limits=None):
    """Add an 'analysis' entry to a measured layout and return it. norms:
    usual values of the deck (deck_norms), for the consistency checks;
    limits: max_words, min_font of find_density_warnings."""
    norms = norms or {}
    blocks, area = _visible(layout['blocks']), layout['area']
    bottom = max((_rect(b)[3] for b in blocks), default=area['y'])
    collisions, tight, intentional = find_overlaps(blocks, threshold)
    hidden_text = find_hidden_text(blocks)
    # a collision between a text and the block hiding it is reported once, as hidden text
    hiding = {frozenset((h['id'], h['by'])) for h in hidden_text}
    collisions = [c for c in collisions if frozenset((c['a'], c['b'])) not in hiding]
    layout['analysis'] = {
        'collisions': collisions,
        'hidden_text': hidden_text,
        'out_of_area': find_out_of_area(blocks, area, threshold, layout.get('scrolling', False)),
        'clipped': find_clipped(blocks, threshold),
        'upscaled_images': find_upscaled_images(blocks),
        'tight': tight,
        'intentional': intentional,
        'background_overlaps': find_background_overlaps(blocks, collisions + intentional, threshold),
        'gaps': vertical_gaps(blocks),  # spacers count as gaps
        'free_bottom': area['y'] + area['h'] - bottom,
        'occupancy': round(occupancy(blocks, area), 2),
        'near_aligned': find_near_alignments(blocks, area, norms.get('columns', ())),
        'density': density(blocks, area),
        'deviations': find_deviations(blocks, norms) if norms else [],
    }
    # the limits are meant for slides, not for scrolling web pages
    layout['analysis']['dense'] = [] if layout.get('scrolling') else \
        find_density_warnings(layout['analysis']['density'], **(limits or {}))
    return layout['analysis']


PROBLEM_KEYS = ('collisions', 'hidden_text', 'out_of_area', 'clipped', 'upscaled_images')


WARNING_KEYS = ('tight', 'near_aligned', 'dense')


def count_problems(analysis):
    return sum(len(analysis.get(k, [])) for k in PROBLEM_KEYS)


def count_warnings(analysis):
    return sum(len(analysis.get(k, [])) for k in WARNING_KEYS)


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def _md_cell(text):
    return str(text).replace('|', '\\|').replace('\n', ' ')


def _zone(o):
    return f"x {o['x0']}..{o['x1']}, y {o['y0']}..{o['y1']}"


def page_markdown(name, source, layout):
    """Markdown report of one page."""
    area, analysis = layout['area'], layout['analysis']
    lines = [f'# {name}', '',
             f'Source: `{source}`', '',
             f"Usable area: x {area['x']}..{area['x'] + area['w']}, y {area['y']}..{area['y'] + area['h']} "
             f"({area['w']}×{area['h']} px) · occupancy {round(100 * analysis['occupancy'])} % "
             f"· free space at the bottom {analysis['free_bottom']} px", '',
             'Positions and sizes bound the ink of each block: what is actually drawn '
             '(text lines, images reduced to their drawn shape, backgrounds, borders). '
             'Overlaps are computed on the ink rectangles themselves (layout.json: "ink"), '
             'so the empty corners of a block do not count. Spacers are empty blocks.', '',
             '| # | kind | x, y | w × h | margins (t r b l) | position | font | signature |',
             '|---|------|------|-------|-------------------|----------|------|-----------|']
    for b in layout['blocks']:
        x0, y0, x1, y1 = _rect(b)
        kind = b['kind'] + (' (overlay)' if b.get('intentional') else '')
        lines.append(f"| {b['id']} | {kind} | {x0}, {y0} | {x1 - x0} × {y1 - y0} | "
                     f"{' '.join(str(m) for m in b['margin'])} | {b['position']} | {b['font_size']} | "
                     f"{_md_cell(b['signature'])} |")

    problems = []
    for h in analysis.get('hidden_text', []):
        problems.append(f"- HIDDEN TEXT #{h['id']} under #{h['by']}: {_zone(h)} "
                        f"({round(100 * h['fraction'])} % of the text of #{h['id']} is covered)")
    for c in analysis['collisions']:
        problems.append(f"- COLLISION #{c['a']} × #{c['b']}: {_zone(c)} ({c['area']} px² of drawn content)")
    for o in analysis['out_of_area']:
        sides = ', '.join(f'{v} px {k}' for k, v in o.items() if k != 'id')
        problems.append(f"- OUT OF AREA #{o['id']}: {sides}")
    for c in analysis['clipped']:
        problems.append(f"- CLIPPED #{c['id']}: {c['w']} px (width) / {c['h']} px (height) of content hidden")
    for u in analysis['upscaled_images']:
        problems.append(f"- UPSCALED IMAGE #{u['id']}: {u['src']} displayed at ×{u['scale']} (blurry)")
    lines += ['', '## Problems', ''] + (problems or ['None.'])

    warnings = [f"- TIGHT #{t['a']} × #{t['b']}: line box of text overlapping by {t['y1'] - t['y0']} px "
                f"({_zone(t)}); the glyphs probably do not touch, but the spacing is tight"
                for t in analysis.get('tight', [])]
    warnings += [f"- NEAR-ALIGNED #{n['id']}: {n['edge']} at {n['axis']} {n['value']}, "
                 f"{abs(n['delta'])} px {_direction(n)} the {n['ref_label']} ({n['axis']} {n['ref']})"
                 for n in analysis.get('near_aligned', [])]
    dense_text = {'words': 'words of text', 'min_font': 'px: smallest font size'}
    warnings += [f"- {'SMALL FONT' if d['kind'] == 'min_font' else 'DENSE'}: {d['value']} {dense_text[d['kind']]} "
                 f"({'minimum' if d['kind'] == 'min_font' else 'limit'} {d['limit']})"
                 for d in analysis.get('dense', [])]
    if warnings:
        lines += ['', '## Warnings', ''] + warnings

    deviations = [_deviation_text(d) for d in analysis.get('deviations', [])]
    if deviations:
        lines += ['', '## Differences with the rest of the deck', ''] + deviations

    notes = [f"- #{c['a']} × #{c['b']} overlap ({_zone(c)}): marked as intentional (class overlay)"
             for c in analysis.get('intentional', [])]
    notes += [f"- #{o['other']} overlaps only the background (uniform or transparent) of image "
              f"{o['src']} in #{o['image']}: not visible, but the image box is reserved there"
              for o in analysis.get('background_overlaps', [])]
    if notes:
        lines += ['', '## Notes', ''] + notes

    if 'density' in analysis:
        d = analysis['density']
        lines += ['', '## Density', '',
                  f"{d['words']} words, {d['formulas']} formulas, {d['code_lines']} lines of code, "
                  f"{d['items']} list items, {d['text_lines']} lines of text; smallest font "
                  f"{d['min_font'] if d['min_font'] is not None else '-'} px; text covers "
                  f"{round(100 * d['text_area'])} %, images {round(100 * d['media_area'])} % of the area"]

    if analysis.get('lint'):
        lines += ['', '## Values written by hand (design lint)', '',
                  'Replace them with the layout or macro given (see structure/design.md of the site):', '']
        lines += [f"- line {f['line']}, {f['kind']}: `{f['text']}` -> {f['advice']}" for f in analysis['lint']]

    if analysis['gaps']:
        lines += ['', '## Vertical gaps between in-flow blocks', '',
                  ', '.join(f'#{a}→#{b}: {g} px' for a, b, g in analysis['gaps'])]
    return '\n'.join(lines) + '\n'


def _direction(n):
    if n['axis'] == 'x':
        return 'right of' if n['delta'] > 0 else 'left of'
    return 'below' if n['delta'] > 0 else 'above'


def _deviation_text(d):
    if d['kind'] == 'title_position':
        return (f"- TITLE POSITION #{d['id']}: {d['anchor'][0]} x {d['value'][0]}, {d['anchor'][1]} y "
                f"{d['value'][1]}; usual {d['norm'][0]}, {d['norm'][1]}")
    if d['kind'] == 'title_variant':
        return f"- TITLE VARIANT #{d['id']}: {d['value']}; usual page titles: {d['norm']}"
    if d['kind'] == 'title_gap':
        return f"- TITLE GAP #{d['id']}: {d['value']} px below the title; usual {d['norm']} px"
    return (f"- TEXT FONT #{d['id']}: text at {d['value']} px; usual text sizes "
            f"{', '.join(map(str, d['norm']))} px")


def norms_markdown(norms):
    """Markdown description of the usual values of a deck."""
    if norms.get('pages', 0) < 3:
        return ''
    lines = ['## Deck style (usual values over all pages)', '']
    for t in norms['titles']:
        lines.append(f"- page title `{t['tag']}` {t['font']} px ({t['pages']} pages): {t['x_anchor']} x {t['x']}, "
                     f"{t['y_anchor']} y {t['y']}")
    if norms['columns']:
        lines.append('- columns (x of left edges shared by many pages): ' + ', '.join(map(str, norms['columns'])))
    if norms['body_font']:
        lines.append(f"- body text: {norms['body_font']} px; text sizes used on several pages: "
                     f"{', '.join(map(str, norms['text_fonts']))} px")
    if norms['title_gap'] is not None:
        lines.append(f"- gap below the page title: {norms['title_gap']} px")
    if norms['words'] is not None:
        lines.append(f"- words per page: {norms['words']} (median)")
    if norms['occupancy'] is not None:
        lines.append(f"- occupancy: {round(100 * norms['occupancy'])} % (median)")
    return '\n'.join(lines) + '\n'


SUMMARY_HEADER = '''# Layout summary

One section per page in `<page>/layout.md` (block table + problems), with
`<page>/overlay.png` (real render, outlined ink of each block, hidden text
dashed) and `<page>/blocks.png` (ink as solid rectangles). Coordinates are
CSS pixels, origin at the top-left corner of the page; "usable area" is the
inside of the slide frame. Block numbers (#) match the images. A block is
found in the source with its signature (tag, inline style, beginning of text,
image names).

Problems: HIDDEN TEXT (text covered by another block drawn on top of it),
COLLISION (drawn content of two blocks overlapping), OUT OF AREA (block
beyond the usable area), CLIPPED (content cut by overflow), UPSCALED IMAGE
(bitmap displayed larger than its native size: blurry).
Warnings: TIGHT (text very close to another block: line boxes overlap, glyphs
probably do not), NEAR-ALIGNED (edge or center a few px away from that of
another block, of the area or of a column of the deck: align it exactly or
move it clearly), DENSE (too many words), SMALL FONT.
Differences with the deck (deviations): page title not at its usual position,
or of an unusual kind or size, unusual gap below the title, text in a font
size used nowhere else.
These are not errors, but breaks of consistency to check.
`contact_NN.png`: thumbnails of all pages in deck order (n), to see the
whole deck at once; badges P (problems), W (warnings), D (deviations).
An overlap is intentional when one of the blocks has the class `overlay`
(LHTML: `::(.overlay)[...]`): it is listed in the notes, not as a problem.
'''


def summary_markdown(rows, norms=None, design=None):
    """rows: (name, report path, analysis) in deck order; design: path of the
    reference of the design (macros and tokens), relative to the summary."""
    lines = [SUMMARY_HEADER]
    if design:
        lines.append(f'Macros and tokens of the design (use them instead of inline styles): '
                     f'`{design}`.\n')
    if norms:
        lines.append(norms_markdown(norms))
    debt = sum(len(r[2].get('lint', [])) for r in rows)
    if debt:
        lines.append(f"Values written by hand (design lint, column `lint`): {debt} in "
                     f"{sum(1 for r in rows if r[2].get('lint'))} of {len(rows)} pages; each page report "
                     f"gives the layout or macro that replaces them.\n")
    lines += ['| n | page | problems | hidden text | collisions | out of area | clipped | upscaled | warnings '
              '| deviations | lint | words | min font | occupancy | report |',
              '|---|------|----------|-------------|------------|-------------|---------|----------|----------'
              '|------------|------|-------|----------|-----------|--------|']
    numbered = [(n, *row) for n, row in enumerate(rows, 1)]
    for n, name, report_path, a in sorted(numbered, key=lambda r: (-count_problems(r[3]), -count_warnings(r[3]), r[0])):
        d = a.get('density') or {}
        lines.append(f"| {n} | {name} | {count_problems(a)} | {len(a.get('hidden_text', []))} | "
                     f"{len(a['collisions'])} | {len(a['out_of_area'])} | {len(a['clipped'])} | "
                     f"{len(a['upscaled_images'])} | {count_warnings(a)} | {len(a.get('deviations', []))} | "
                     f"{len(a.get('lint', []))} | "
                     f"{d.get('words', '-')} | {d.get('min_font') or '-'} | "
                     f"{round(100 * a['occupancy'])} % | [layout.md]({report_path}) |")
    return '\n'.join(lines) + '\n'


def contact_sheets_html(rows, viewport, columns=4, rows_per_sheet=4):
    """HTML pages of thumbnails of the pages (render.png), in deck order.
    rows: (name, page directory relative to the output directory, analysis).
    Returns a list of HTML strings."""
    per_sheet = columns * rows_per_sheet
    sheets = []
    for start in range(0, len(rows), per_sheet):
        cells = []
        for n, (name, rel_dir, a) in enumerate(rows[start:start + per_sheet], start + 1):
            badges = ''.join(f'<span class="{c}">{l}{v}</span>' for c, l, v in
                             (('p', 'P', count_problems(a)), ('w', 'W', count_warnings(a)),
                              ('d', 'D', len(a.get('deviations', [])))) if v)
            name_html = name.replace('&', '&amp;').replace('<', '&lt;')
            cells.append(f'<figure><img src="{rel_dir}/render.png"><figcaption><b>{n}</b> {name_html} '
                         f'{badges}</figcaption></figure>')
        sheets.append(f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{ margin: 0; padding: 12px; background: #444; font: 18px sans-serif; color: white; }}
main {{ display: grid; grid-template-columns: repeat({columns}, minmax(0, 1fr)); gap: 12px; }}
figure {{ margin: 0; }}
img {{ width: 100%; aspect-ratio: {viewport['w']} / {viewport['h']}; object-fit: cover; object-position: top;
       display: block; background: white; }}
figcaption {{ padding: 4px 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
span {{ margin-left: 6px; padding: 0 6px; border-radius: 4px; font-weight: bold; }}
.p {{ background: #d62728; }} .w {{ background: #e08000; }} .d {{ background: #1f6fd0; }}
</style></head><body><main>
{chr(10).join(cells)}
</main></body></html>
''')
    return sheets


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

def _options(meta):
    options = dict(DEFAULTS)
    options.update((meta.get('plugin_arg') or {}).get('layout_report') or {})
    return options


def _run_node(script, arguments):
    cmd = ['node', path_current_file + 'assets/' + script] + arguments
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError('node not found: install Node.js, then run `npm install` '
                           'in the static_website_lhtml directory')
    if 'Cannot find module' in proc.stderr:
        raise RuntimeError('puppeteer not found: run `npm install` in the static_website_lhtml directory')
    if proc.returncode:
        raise RuntimeError(f'{script} failed ({proc.returncode}): {proc.stderr.strip()}')
    return proc


def write_contact_sheets(output_dir, rows, viewport, options, log, changed=None):
    """Write contact_NN.html and screenshot them as contact_NN.png (only the
    sheets showing the pages `changed`, a set of row indices, when given)."""
    sheets = []
    per_sheet = options['contact_columns'] * options['contact_rows']
    for i, html in enumerate(contact_sheets_html(rows, viewport, options['contact_columns'],
                                                 options['contact_rows']), 1):
        if changed is not None and not any((i - 1) * per_sheet <= k < i * per_sheet for k in changed):
            continue
        html_path = os.path.abspath(os.path.join(output_dir, f'contact_{i:02d}.html'))
        with open(html_path, 'w', encoding='utf-8', errors='replace') as fid:
            fid.write(html)
        sheets.append({'html': html_path, 'png': html_path[:-len('.html')] + '.png'})
    if not sheets:
        return
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fid:
        json.dump(sheets, fid)
        sheets_json = fid.name
    try:
        proc = _run_node('layout_contact.js', [f'--input={sheets_json}'])
        for line in proc.stderr.splitlines():
            if line.startswith('layout_contact:'):
                log.error(line)
    finally:
        os.remove(sheets_json)


def post_process(meta):
    options = _options(meta)
    log = meta['log']
    site_dir = meta['site_directory']
    output_dir = str(layout_output_directory(meta))
    built = {entry['dir'] + entry['filename'] for entry in built_pages(meta)}
    partial = len(built) < len(structure(meta))     # --only: the others keep their report

    pages, previous = [], []
    for entry in structure(meta):
        relative = entry['dir'] + entry['filename']
        if os.path.isabs(relative) or '..' in relative.replace('\\', '/').split('/'):
            raise ValueError(f'Invalid page path in layout structure: {relative}')
        html = site_dir + relative
        page = {'html': os.path.abspath(html),
                'out': os.path.abspath(os.path.join(output_dir, 'pages', entry['dir'], entry['filename'])),
                'name': relative, 'source': entry['src'], 'layout': entry.get('layout')}
        if relative not in built:
            if partial and os.path.isfile(os.path.join(page['out'], 'layout.json')):
                previous.append(page)
        elif os.path.isfile(html):
            pages.append(page)

    if os.path.isdir(output_dir) and not partial:
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    log.keyvalue('*', f'Measure layout of {len(pages)} pages ...', indent_level=2)
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fid:
        json.dump([{'html': p['html'], 'out': p['out']} for p in pages], fid)
        pages_json = fid.name
    try:
        proc = _run_node('layout_measure.js', [
            f'--input={pages_json}', f"--root={options['root']}", f"--exclude={options['exclude']}",
            f"--width={options['width']}", f"--height={options['height']}",
            f"--images={1 if options['images'] else 0}"])
        for line in proc.stderr.splitlines():
            if line.startswith('layout_measure:'):
                log.error(line)
    finally:
        os.remove(pages_json)

    measured = []
    for p in previous + pages:
        layout_path = os.path.join(p['out'], 'layout.json')
        if os.path.isfile(layout_path):
            with open(layout_path, encoding='utf-8') as fid:
                measured.append((p, layout_path, json.load(fid)))
    norms = deck_norms([layout for _, _, layout in measured])
    limits = {k: options[k] for k in ('max_words', 'min_font')}

    rows = []
    linter = Linter(meta['design']) if meta.get('design') else None
    order = {entry['dir'] + entry['filename']: k for k, entry in enumerate(structure(meta))}
    measured.sort(key=lambda m: order[m[0]['name']])
    for p, layout_path, layout in measured:
        if p in previous:           # analysed by its build
            rows.append((p['name'], os.path.relpath(os.path.join(p['out'], 'layout.md'), output_dir),
                         layout['analysis']))
            continue
        analyse(layout, options['threshold'], norms, limits)
        if linter is not None and os.path.isfile(p['source']):
            layout['analysis']['lint'] = [f.as_dict() for f in linter.lint_file(p['source'], p['layout'])]
        layout['source'] = os.path.relpath(p['source'], meta.get('config_directory') or '.')
        with open(layout_path, 'w') as fid:
            json.dump(layout, fid, indent=1)
        with open(os.path.join(p['out'], 'layout.md'), 'w', encoding='utf-8', errors='replace') as fid:
            fid.write(page_markdown(p['name'], layout['source'], layout))
        rows.append((p['name'], os.path.relpath(os.path.join(p['out'], 'layout.md'), output_dir),
                     layout['analysis']))

    with open(os.path.join(output_dir, 'summary.md'), 'w', encoding='utf-8', errors='replace') as fid:
        reference = os.path.join(meta.get('published_site_directory') or site_dir, 'structure', 'design.md')
        fid.write(summary_markdown(rows, norms, design=os.path.relpath(reference, output_dir)
                                   if meta.get('design') and any(meta['design'].values()) else None))
    with open(os.path.join(output_dir, 'deck.json'), 'w') as fid:
        json.dump(norms, fid, indent=1)
    if options['images'] and measured:
        write_contact_sheets(output_dir, [(p['name'], os.path.relpath(p['out'], output_dir), layout['analysis'])
                                          for p, _, layout in measured],
                             measured[0][2]['viewport'], options, log,
                             changed={k for k, (p, _, _) in enumerate(measured) if p not in previous}
                             if partial else None)

    n_problems = sum(count_problems(r[2]) for r in rows)
    log.keyvalue('info', f"Layout report: {len(pages)} measured, {len(rows)} pages, {n_problems} problems -> "
                         f"{os.path.relpath(os.path.join(output_dir, 'summary.md'))}", indent_level=2)
    if len(rows) < len(pages) + len(previous):
        raise RuntimeError(f'layout measurement failed for {len(pages) + len(previous) - len(rows)} page(s)')
