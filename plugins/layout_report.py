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
    internal-overlay.png  real render with the inner blocks outlined

<config_dir>/.layout/summary.md lists all pages sorted by number of problems,
with the usual values of the deck (title position, columns, body font size,
...: also in deck.json), and contact_NN.png shows thumbnails of all pages. Coordinates are in CSS pixels, origin at the top-left corner of
the page (1920x1080 for slides). One build at a time writes the report
(lib/report_lock.py); --verify adds the outputs of the agent extension
(agent/report.py).

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
        min_font: 20         # SMALL FONT below this font size (px), slides only,
                             # when design_rules is disabled
        contact_columns: 4   # thumbnails per row / rows per contact sheet
        contact_rows: 4
        design_rules: {...}  # DESIGN checks by role (lib/design_checks.py)
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading

from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Column

from lib import dependencies
from lib.design_checks import analyse_design, validate as validate_design_rules
from lib.lint import Linter
from lib.report_lock import report_lock
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
            width = (m.get('drawn') or {}).get('w') or m['w']      # drawn size (object-fit)
            if width > m['natural_w'] * tolerance:
                result.append({'id': b['id'], 'src': m['src'], 'scale': round(width / m['natural_w'], 2)})
    return result


def find_collapsed(blocks, minimum=8):
    """Images and videos that have a size of their own but are drawn
    (almost) without width or height, e.g. in a flex box without a height:
    {id, src, w, h}."""
    return [{'id': b['id'], 'src': m['src'], 'w': m['w'], 'h': m['h']}
            for b in blocks for m in b.get('media', [])
            if m.get('natural_w', 0) >= minimum and m.get('natural_h', 0) >= minimum
            and (m['w'] < minimum or m['h'] < minimum)]


def find_svg_overflow(blocks, threshold=4):
    """SVG figures drawing beyond their viewBox: what is beyond is cut when
    the figure is shown as an image. {id, src, left, top, right, bottom} (px
    as displayed)."""
    found = []
    for b in blocks:
        for f in b.get('svg', []):
            o = f.get('overflow') or {}
            if any(v > threshold for v in o.values()):
                found.append({'id': b['id'], 'src': f['src'], **o})
    return found


def find_svg_labels(blocks):
    """Labels (text) of SVG figures drawn across a line of the figure, without
    a halo (paint-order: stroke) that would keep them readable: one entry per
    figure, {id, src, texts (the first ones), count, over}."""
    found = []
    for b in blocks:
        for f in b.get('svg', []):
            labels = f.get('labels', [])
            if labels:
                found.append({'id': b['id'], 'src': f['src'], 'texts': [l['text'] for l in labels[:3]],
                              'count': len(labels), 'over': labels[0]['over']})
    return found


def find_reserved_overlaps(blocks, reserved, threshold=4):
    """Blocks whose ink covers an area reserved by the theme (the
    navigation): {id, name, x0, y0, x1, y1}."""
    found = []
    for zone in reserved or []:
        z = (zone['x'], zone['y'], zone['x'] + zone['w'], zone['y'] + zone['h'])
        for b in blocks:
            parts = [o for r in _ink(b) if (o := _overlap(r, z, threshold))]
            if parts:
                bounds = _bounds(parts)
                found.append({'id': b['id'], 'name': zone.get('name', 'reserved'),
                              **{k: bounds[k] for k in ('x0', 'y0', 'x1', 'y1')}})
    return found


def find_wrapped(blocks, short=0.3):
    """Titles written on several lines, and list items or credits whose last
    line holds only a few words (shorter than `short` × the first line)."""
    found = []
    for b in blocks:
        for w in b.get('wrapped', []):
            title = w['tag'][0] == 'h'
            if title or (w['lines'] == 2 and w['last_w'] < short * w['first_w']):
                found.append({'id': b['id'], **w})
    return found


def find_row_misalignments(blocks, tolerance=2, intended=40):
    """Rows of figures side by side whose tops or bottoms differ by a few
    pixels (more than `tolerance`, up to `intended`: beyond, deliberate)."""
    found = []
    for b in blocks:
        for row in b.get('rows', []):
            for edge in ('tops', 'bottoms'):
                spread = max(row[edge]) - min(row[edge])
                if tolerance < spread <= intended:
                    found.append({'id': b['id'], 'edge': edge[:-1], 'figures': row['figures'],
                                  'values': row[edge], 'spread': spread})
                    break
    return found


def find_fit(blocks, empty=0.25, cropped=0.05):
    """Figures drawn much smaller than their box (object-fit contain: empty
    bands) or cropped (cover)."""
    found = []
    for b in blocks:
        for m in b.get('media', []):
            d, box = m.get('drawn'), m.get('box')
            if not d or not box or not box['w'] or not box['h'] or m.get('vector'):
                continue        # an SVG fills its area on purpose (media::)
            ratio = d['w'] * d['h'] / (box['w'] * box['h'])
            if d['fit'] == 'cover' and ratio > 1 / (1 - cropped):
                cut = 'left and right' if d['w'] > box['w'] else 'top and bottom'
                found.append({'id': b['id'], 'src': m['src'], 'kind': 'cropped',
                              'part': round(1 - 1 / ratio, 2), 'sides': cut})
            elif d['fit'] != 'cover' and ratio < 1 - empty:
                bands = 'left and right' if d['w'] < box['w'] - 2 else 'top and bottom'
                found.append({'id': b['id'], 'src': m['src'], 'kind': 'small',
                              'part': round(ratio, 2), 'sides': bands})
    return found


def coverage(rects, area, step=10, rows=None):
    """Grid of the usable area, one cell per `step` px: rows of bytes, 1 where
    the centre of the cell is inside one of the rectangles (x0, y0, x1, y1).
    Filled rectangle by rectangle (in `rows` when given): shared by occupancy
    and largest_free_rect."""
    off = step // 2
    # the cells whose centre is inside the area
    nx, ny = (max(0, -(-(area[k] - off) // step)) for k in ('w', 'h'))
    if rows is None:
        rows = [bytearray(nx) for _ in range(ny)]
    cell = lambda v, origin, n: min(n, max(0, -(-(v - origin - off) // step)))  # first centre >= v
    for x0, y0, x1, y1 in rects:
        i0, i1 = cell(x0, area['x'], nx), cell(x1, area['x'], nx)
        if i1 > i0:
            ones = b'\x01' * (i1 - i0)
            for j in range(cell(y0, area['y'], ny), cell(y1, area['y'], ny)):
                rows[j][i0:i1] = ones
    return rows


def _ink_rects(blocks):
    return [r[:4] for b in blocks for r in _ink(b)]


def _reserved_rects(reserved):
    return [(z['x'], z['y'], z['x'] + z['w'], z['y'] + z['h']) for z in reserved or []]


def _covered_share(rows):
    total = sum(len(r) for r in rows)
    return sum(r.count(1) for r in rows) / total if total else 0.0


def _free_rect(rows, area, step=10):
    """Largest rectangle of empty cells (histogram method)."""
    nx, ny = (len(rows[0]), len(rows)) if rows else (0, 0)
    heights, best = [0] * nx, (0, 0, 0, 0, 0)        # area, column, row, width, height
    for j, row in enumerate(rows):
        for i in range(nx):
            heights[i] = 0 if row[i] else heights[i] + 1
        stack = []
        for i in range(nx + 1):
            h = heights[i] if i < nx else 0
            start = i
            while stack and stack[-1][1] >= h:
                start, sh = stack.pop()
                if sh * (i - start) > best[0]:
                    best = (sh * (i - start), start, j - sh + 1, i - start, sh)
            stack.append((start, h))
    if not best[0]:
        return None
    _, i, j, w, h = best
    return {'x': area['x'] + i * step, 'y': area['y'] + j * step, 'w': w * step, 'h': h * step,
            'share': round(w * h / (nx * ny), 2)}


def largest_free_rect(blocks, area, step=10, reserved=()):
    """Largest rectangle of the usable area without ink (nor reserved area):
    {x, y, w, h, share}, on a grid of `step` px."""
    return _free_rect(coverage(_ink_rects(blocks) + _reserved_rects(reserved), area, step), area, step)


def vertical_gaps(blocks):
    """Gaps between consecutive in-flow blocks, top to bottom: [(id_above, id_below, gap px)]."""
    flow = sorted((b for b in blocks if b.get('position') in FLOW_POSITIONS), key=lambda b: _rect(b)[1])
    return [(a['id'], b['id'], _rect(b)[1] - _rect(a)[3]) for a, b in zip(flow, flow[1:])]


def occupancy(blocks, area, step=10):
    """Fraction of the usable area covered by the ink of the blocks (sampled on a grid)."""
    return _covered_share(coverage(_ink_rects(blocks), area, step))


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
    norms['occupancy'] = round(_median([l['analysis']['occupancy'] if 'analysis' in l else occupancy(blocks, l['area'])
                                        for blocks, l in zip(pages, layouts)]), 2)
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


def find_internal(layout, threshold=4):
    nodes = layout.get('subblocks', [])
    by_id = {b['id']: b for b in nodes}
    def ancestors(b):
        result = set()
        while b.get('parent') in by_id:
            b = by_id[b['parent']]
            result.add(b['id'])
        return result
    parents = {b['id']: ancestors(b) for b in nodes}
    collisions, tight, intentional = [], [], []
    visible = [b for b in nodes if b.get('ink')]
    for i, a in enumerate(visible):
        for b in visible[i + 1:]:
            if a['owner'] != b['owner'] or a['legacy_block'] != b['legacy_block']:
                continue  # already covered by aggregate block analysis
            aa, bb = dict(a), dict(b)
            if a['id'] in parents[b['id']]:
                aa['ink'] = [r for r in a['ink'] if r.get('t') != 'paint']
            if b['id'] in parents[a['id']]:
                bb['ink'] = [r for r in b['ink'] if r.get('t') != 'paint']
            if not aa['ink'] or not bb['ink']:
                continue
            hard, soft, intended = find_overlaps([aa, bb], threshold)
            collisions.extend(hard); tight.extend(soft); intentional.extend(intended)
    overflow = []
    for b in visible:
        if b.get('intentional') or b.get('position') in ('absolute', 'fixed'):
            continue
        # Explicit column boundaries are meaningful even when CSS overflow is visible.
        parent = by_id.get(b.get('parent'))
        while parent and parent.get('role') != 'column':
            parent = by_id.get(parent.get('parent'))
        if not parent:
            continue
        if parent.get('overflow', 'visible') != 'visible':
            continue  # report the clipping once instead
        f = parent['frame']
        x0, y0, x1, y1 = _rect(b)
        sides = {'left': f['x'] - x0, 'right': x1 - f['x'] - f['w']}
        sides = {k: round(v, 2) for k, v in sides.items() if v > threshold}
        if sides:
            overflow.append({'id': b['id'], 'parent': parent['id'], **sides})
    nested = [b for b in nodes if b.get('parent')]
    return {'internal_collisions': collisions, 'internal_tight': tight,
            'internal_intentional': intentional, 'internal_overflow': overflow,
            'internal_clipped': find_clipped(nested, threshold)}


def analyse(layout, threshold=4, norms=None, limits=None, design_rules=None):
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
    grid = coverage(_ink_rects(blocks), area)          # occupancy, then free area (with the reserved areas)
    covered = _covered_share(grid)
    coverage(_reserved_rects(layout.get('reserved')), area, rows=grid)
    layout['analysis'] = {
        'reserved': find_reserved_overlaps(blocks, layout.get('reserved'), threshold),
        'collisions': collisions,
        'hidden_text': hidden_text,
        'out_of_area': find_out_of_area(blocks, area, threshold, layout.get('scrolling', False)),
        'clipped': find_clipped(blocks, threshold),
        'upscaled_images': find_upscaled_images(blocks),
        'collapsed': find_collapsed(blocks),
        'svg_overflow': find_svg_overflow(blocks, threshold),
        'svg_labels': find_svg_labels(blocks),
        'tight': tight,
        'intentional': intentional,
        'background_overlaps': find_background_overlaps(blocks, collisions + intentional, threshold),
        'gaps': vertical_gaps(blocks),  # spacers count as gaps
        'free_bottom': area['y'] + area['h'] - bottom,
        'occupancy': round(covered, 2),
        'near_aligned': find_near_alignments(blocks, area, norms.get('columns', ())),
        'density': density(blocks, area),
        'wrapped': find_wrapped(blocks),
        'rows': find_row_misalignments(blocks),
        'fit': find_fit(blocks),
        'free': _free_rect(grid, area),
        'deviations': find_deviations(blocks, norms) if norms else [],
    }
    layout['analysis'].update(find_internal(layout, threshold))
    # A canvas box is not a paint mask. Its overlap cannot prove hidden text,
    # notably for pointer-events:none labels and controls layered over a scene.
    canvas = {b['id'] for b in layout['blocks'] + layout.get('subblocks', []) if b.get('unverified_canvas')}
    uncertain = []
    for key in ('collisions', 'hidden_text', 'internal_collisions'):
        confirmed = []
        for finding in layout['analysis'].get(key, []):
            ids = {finding.get(k) for k in ('id', 'a', 'b', 'by')}
            if ids & canvas:
                uncertain.append(dict(finding, kind=key, reason='Canvas bounds do not establish painted or occluded pixels; inspect the render.'))
            else:
                confirmed.append(finding)
        layout['analysis'][key] = confirmed
    layout['analysis']['canvas_overlaps'] = uncertain

    # the limits are meant for slides, not for scrolling web pages
    layout['analysis']['dense'] = [] if layout.get('scrolling') else \
        find_density_warnings(layout['analysis']['density'], **(limits or {}))
    layout['analysis']['role_design'], layout['design_checks'] = analyse_design(layout, design_rules)
    if layout.get('design_measurement') and layout['design_checks']['enabled']:
        layout['analysis']['dense'] = [d for d in layout['analysis']['dense'] if d['kind'] != 'min_font']
    return layout['analysis']


PROBLEM_KEYS = ('collisions', 'hidden_text', 'out_of_area', 'clipped', 'upscaled_images', 'reserved',
                'collapsed', 'svg_overflow', 'internal_collisions', 'internal_overflow', 'internal_clipped', 'interactive_errors')


WARNING_KEYS = ('tight', 'near_aligned', 'dense', 'wrapped', 'rows', 'fit', 'svg_labels', 'internal_tight', 'role_design', 'canvas_overlaps')


def count_problems(analysis):
    return sum(len(analysis.get(k, [])) for k in PROBLEM_KEYS) + analysis.get('nested_problems', 0)


def count_warnings(analysis):
    return sum(len(analysis.get(k, [])) for k in WARNING_KEYS) + analysis.get('nested_warnings', 0)


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def _md_cell(text):
    return str(text).replace('|', '\\|').replace('\n', ' ')


def _zone(o):
    return f"x {o['x0']}..{o['x1']}, y {o['y0']}..{o['y1']}"


def problem_lines(analysis):
    """The problems of a page, one Markdown line each: '- KIND #id ...: details'."""
    problems = []
    for h in analysis.get('hidden_text', []):
        problems.append(f"- HIDDEN TEXT #{h['id']} under #{h['by']}: {_zone(h)} "
                        f"({round(100 * h['fraction'])} % of the text of #{h['id']} is covered)")
    for c in analysis.get('collisions', []):
        problems.append(f"- COLLISION #{c['a']} × #{c['b']}: {_zone(c)} ({c['area']} px² of drawn content)")
    for o in analysis.get('out_of_area', []):
        sides = ', '.join(f'{v} px {k}' for k, v in o.items() if k != 'id')
        problems.append(f"- OUT OF AREA #{o['id']}: {sides}")
    for c in analysis.get('clipped', []):
        problems.append(f"- CLIPPED #{c['id']}: {c['w']} px (width) / {c['h']} px (height) of content hidden")
    for u in analysis.get('upscaled_images', []):
        problems.append(f"- UPSCALED IMAGE #{u['id']}: {u['src']} displayed at ×{u['scale']} (blurry)")
    for r in analysis.get('reserved', []):
        problems.append(f"- RESERVED AREA #{r['id']}: covers the {r['name']} of the theme "
                        f"(x {r['x0']}..{r['x1']}, y {r['y0']}..{r['y1']})")
    for c in analysis.get('collapsed', []):
        problems.append(f"- COLLAPSED FIGURE #{c['id']}: {c['src']} drawn at {c['w']} × {c['h']} px (invisible)")
    for o in analysis.get('svg_overflow', []):
        sides = ', '.join(f'{o[k]} px {k}' for k in ('left', 'top', 'right', 'bottom') if o.get(k, 0) > 0)
        problems.append(f"- SVG OVERFLOW #{o['id']}: {o['src']} draws beyond its viewBox ({sides}): cut when shown")
    for c in analysis.get('internal_collisions', []):
        problems.append(f"- INTERNAL COLLISION #{c['a']} × #{c['b']}: {_zone(c)}")
    for c in analysis.get('internal_clipped', []):
        problems.append(f"- INTERNAL CLIPPED #{c['id']}: {c['w']} px width / {c['h']} px height")
    for c in analysis.get('internal_overflow', []):
        problems.append(f"- COLUMN OVERFLOW #{c['id']} outside #{c['parent']}: " +
                        ', '.join(f"{c[k]} px {k}" for k in ('left', 'right') if k in c))
    problems += [f"- INTERACTIVE STATE {e['kind']}: {e['message']}" for e in analysis.get('interactive_errors', [])]
    return problems


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
             'Line: line of the source where the block starts (- for text directly in the page).', '',
             '| # | line | kind | x, y | w × h | margins (t r b l) | position | font | signature |',
             '|---|------|------|------|-------|-------------------|----------|------|-----------|']
    for b in layout['blocks']:
        x0, y0, x1, y1 = _rect(b)
        kind = b['kind'] + (' (overlay)' if b.get('intentional') else '') \
            + (f" in #{b['inside']}" if b.get('inside') else '')
        lines.append(f"| {b['id']} | {b.get('line') or '-'} | {kind} | {x0}, {y0} | {x1 - x0} × {y1 - y0} | "
                     f"{' '.join(str(m) for m in b['margin'])} | {b['position']} | {b['font_size']} | "
                     f"{_md_cell(b['signature'])} |")

    problems = problem_lines(analysis)
    lines += ['', '## Problems', ''] + (problems or ['None.'])

    warnings = [f"- TIGHT #{t['a']} × #{t['b']}: line box of text overlapping by {t['y1'] - t['y0']} px "
                f"({_zone(t)}); the glyphs probably do not touch, but the spacing is tight"
                for t in analysis.get('tight', [])]
    warnings += [f"- INTERNAL TIGHT #{t['a']} × #{t['b']}: {_zone(t)}; inspect text spacing"
                 for t in analysis.get('internal_tight', [])]
    warnings += [f"- NEAR-ALIGNED #{n['id']}: {n['edge']} at {n['axis']} {n['value']}, "
                 f"{abs(n['delta'])} px {_direction(n)} the {n['ref_label']} ({n['axis']} {n['ref']})"
                 for n in analysis.get('near_aligned', [])]
    for w in analysis.get('wrapped', []):
        what = 'title' if w['tag'][0] == 'h' else ('credit' if w['tag'].endswith('credit') else 'list item')
        tail = '' if what == 'title' else f", the last one {w['last_w']} px wide (first {w['first_w']} px)"
        warnings.append(f"- WRAPPED #{w['id']}: {what} \"{w['text']}\" on {w['lines']} lines{tail}")
    for r in analysis.get('rows', []):
        values = ', '.join(f'{f} {v}' for f, v in zip(r['figures'], r['values']))
        warnings.append(f"- ROW #{r['id']}: the {r['edge']}s of the figures side by side differ by "
                        f"{r['spread']} px ({values})")
    for f in analysis.get('fit', []):
        warnings.append(f"- {'CROPPED' if f['kind'] == 'cropped' else 'SMALL IN ITS BOX'} #{f['id']}: {f['src']} "
                        + (f"{round(100 * f['part'])} % cut ({f['sides']})" if f['kind'] == 'cropped'
                           else f"drawn on {round(100 * f['part'])} % of its box (empty {f['sides']})"))
    for f in analysis.get('svg_labels', []):
        texts = ', '.join(f'"{t}"' for t in f['texts']) + (f" and {f['count'] - len(f['texts'])} more"
                                                          if f['count'] > len(f['texts']) else '')
        what = 'is' if f['count'] == 1 else 'are'
        warnings.append(f"- SVG LABEL #{f['id']}: in {f['src']}, {texts} {what} drawn across a {f['over']} "
                        f"(move it, or give it a halo: paint-order=\"stroke\" stroke=\"white\")")
    dense_text = {'words': 'words of text', 'min_font': 'px: smallest font size'}
    warnings += [f"- {'SMALL FONT' if d['kind'] == 'min_font' else 'DENSE'}: {d['value']} {dense_text[d['kind']]} "
                 f"({'minimum' if d['kind'] == 'min_font' else 'limit'} {d['limit']})"
                 for d in analysis.get('dense', [])]
    warnings += [f"- DESIGN {d['kind']} #{d['id']} ({d['role']}): {d['value']} vs {d['limit']}; {d['advice']}"
                 for d in analysis.get('role_design', [])]
    warnings += [f"- CANVAS OVERLAP {_zone(d)}: {d['reason']}" for d in analysis.get('canvas_overlaps', [])]
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
        free = analysis.get('free')
        if free:
            lines.append(f"Largest free area: x {free['x']}..{free['x'] + free['w']}, y {free['y']}..{free['y'] + free['h']} "
                         f"({free['w']}×{free['h']} px, {round(100 * free['share'])} % of the area)")

    if analysis.get('lint'):
        lines += ['', '## Values written by hand (design lint)', '',
                  'Replace them with the layout or macro given (see structure/design.md of the site):', '']
        lines += [f"- line {f['line']}, {f['kind']}: `{f['text']}` -> {f['advice']}" for f in analysis['lint']]

    if analysis['gaps']:
        lines += ['', '## Vertical gaps between in-flow blocks', '',
                  ', '.join(f'#{a}→#{b}: {g} px' for a, b, g in analysis['gaps'])]
    if layout.get('freshness'):
        lines += ['', '## Report validity', '', 'Freshness: **' + layout['freshness']['status'] + '**.']
        for change in layout['freshness'].get('changes', []):
            lines.append(f"- {change['kind']}: {change.get('path') or 'page parameters or metadata'}")
    if not layout.get('verification_mode'):     # the sections below: --verify (agent extension)
        return '\n'.join(lines) + '\n'
    if any(b.get('provenance') for b in layout['blocks']):
        lines += ['', '## Source provenance', '', 'Ranges cover observed content; closing-only lines are not included.']
        for b in layout['blocks']:
            if b.get('provenance'):
                origins = ', '.join(f"`{r['file']}:{r['line']}-{r['end_line']}`"
                                    for r in b['provenance']['ranges'])
                lines.append(f"- #{b['id']}: {origins}; anchor `{b.get('stable_id')}`; matching: {b['provenance']['matching']}")
    if layout.get('interactive'):
        info = layout['interactive']
        lines += ['', '## Interactive verification', '',
                  'Each state reloads the initial slide. Samples do not cover every possible interaction.', '']
        if info.get('truncated'):
            lines.append('**Incomplete: state budget exhausted.**')
        for state in info['states']:
            lines.append(f"- `{state['id']}`: {state['status']}; [report](states/{state['id']}/verification.json)")
            if state.get('error'):
                lines.append('  ' + state['error']['message'])
        lines.append('Controlled: CSS timelines, video seeking and requestAnimationFrame. Native timers and randomness remain uncontrolled.')
    for frame in layout.get('frame_layouts', []):
        lines += ['', f"Frame `{frame['id']}` ({frame['layout'].get('source')}): "
                  f"[report](frames/{frame['id']}/verification.json). Canvas semantics are not verified."]
    if layout.get('subblocks'):
        lines += ['', '## Internal hierarchy', '',
                  'Owned ink excludes child content. Source precision is direct or inherited.', '',
                  '| ID | Parent | Role / design role | Source | Precision |', '|---|---|---|---|---|']
        for b in layout['subblocks']:
            lines.append(f"| {b['id']} | {b.get('parent') or '—'} | {b['role']} / {b.get('design_role', '—')} | {_md_cell(b.get('source'))} | {b['source_precision']} |")
        lines += ['', 'Overlay: `internal-overlay.png`.']
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
(bitmap displayed larger than its native size: blurry), RESERVED AREA (content
over the navigation of the theme), COLLAPSED FIGURE (image or video drawn
without width or height), SVG OVERFLOW (SVG figure drawing beyond its viewBox:
cut), INTERNAL COLLISION / INTERNAL CLIPPED (the same between the inner blocks
of a block: items, formulas, captions; see internal-overlay.png), COLUMN
OVERFLOW (content wider than its column).
Warnings: TIGHT (text very close to another block: line boxes overlap, glyphs
probably do not), NEAR-ALIGNED (edge or center a few px away from that of
another block, of the area or of a column of the deck: align it exactly or
move it clearly), DENSE (too many words), DESIGN (text too small for its
role, title not larger than the body, caption far from its figure...; SMALL
FONT when these checks are disabled), CANVAS OVERLAP (text over a canvas:
look at the render), INTERNAL TIGHT, WRAPPED (title on
several lines, or list item with a few words on its second line), ROW (figures
side by side not aligned), SMALL IN ITS BOX / CROPPED (figure much smaller
than its box, or cut, by object-fit), SVG LABEL (text of an SVG figure across
one of its lines).
Renders are reproducible: videos at their first frame, GIFs at their first
image, animations stopped. `changes.md`: what changed since the previous report.
Differences with the deck (deviations): page title not at its usual position,
or of an unusual kind or size, unusual gap below the title, text in a font
size used nowhere else.
These are not errors, but breaks of consistency to check.
`contact_NN.png`: thumbnails of all pages in deck order (n), to see the
whole deck at once; badges P (problems), W (warnings), D (deviations).
An overlap is intentional when one of the blocks has the class `overlay`
(LHTML: `::(.overlay)[...]`): it is listed in the notes, not as a problem.
'''


def _problems_by_key(layout):
    """{(kind, signatures of its blocks): [line]} of the problems of a measure
    (the ids of the blocks change from a measure to the next, not their
    signature; identical blocks have the same key: one line each)."""
    signature = {b['id']: b['signature'] for b in layout.get('blocks', [])}
    found = {}
    for line in problem_lines(layout.get('analysis') or {}):
        head = line.split(':', 1)[0]
        kind = re.match(r'- ([A-Z][A-Z ]*?) #', head)
        key = (kind.group(1) if kind else head, tuple(signature.get(int(i)) for i in re.findall(r'#(\d+)', head)))
        found.setdefault(key, []).append(line)
    return found


def layout_changes(old, new, threshold=4):
    """What changed between two measures of a page: problems that appeared or
    were solved, counts of warnings and lint, blocks moved or resized (matched
    by signature), blocks added or removed. Returns lines of Markdown (none:
    no change)."""
    lines = []
    a, b = old.get('analysis', {}), new.get('analysis', {})
    before, after = _problems_by_key(old), _problems_by_key(new)
    lines += [f'- new problem: {line[2:]}' for key, found in after.items() for line in found[len(before.get(key, [])):]]
    lines += [f'- solved: {line[2:]}' for key, found in before.items() for line in found[len(after.get(key, [])):]]
    for label, count in (('warnings', count_warnings), ('values written by hand', lambda x: len(x.get('lint', [])))):
        if count(a) != count(b):
            lines.append(f'- {label}: {count(a)} -> {count(b)}')
    old_blocks, new_blocks = list(old.get('blocks', [])), list(new.get('blocks', []))
    pairs = []
    # pairs of blocks: same signature, then (text or style changed) same line of
    # the source, or same tag and kind, in order
    for key in (lambda b: b.get('stable_id'), lambda b: b['signature'],
                lambda b: ('line', b['line']) if b.get('line') else None,
                lambda b: (b['kind'], b['signature'].split('[')[0].split(' ')[0], b.get('inside') is not None)):
        for block in list(new_blocks):
            k = key(block)
            match = next((o for o in old_blocks if k is not None and key(o) == k), None)
            if match is not None:
                pairs.append((match, block, match['signature'] != block['signature']))
                old_blocks.remove(match)
                new_blocks.remove(block)
    for before, block, edited in sorted(pairs, key=lambda p: p[1]['id']):
        r0, r1 = _rect(before), _rect(block)
        dx, dy = r1[0] - r0[0], r1[1] - r0[1]
        size0, size1 = (r0[2] - r0[0], r0[3] - r0[1]), (r1[2] - r1[0], r1[3] - r1[1])
        moved = abs(dx) >= threshold or abs(dy) >= threshold
        resized = abs(size1[0] - size0[0]) >= threshold or abs(size1[1] - size0[1]) >= threshold
        if moved or resized or edited:
            change = [f'moved by ({dx:+d}, {dy:+d}) px'] if moved else []
            if resized:
                change.append(f'{size0[0]}×{size0[1]} -> {size1[0]}×{size1[1]} px')
            if edited:
                change.append('text or style changed')
            where = f" (line {block['line']})" if block.get('line') else ''
            lines.append(f"- #{block['id']}{where} {', '.join(change)}: {_md_cell(block['signature'])[:80]}")
    for block in new_blocks:
        where = f" (line {block['line']})" if block.get('line') else ''
        lines.append(f"- new block #{block['id']}{where}: {_md_cell(block['signature'])[:80]}")
    lines += [f"- removed block #{blk['id']}: {_md_cell(blk['signature'])[:80]}" for blk in old_blocks]
    return lines


def changes_markdown(changes, measured):
    """changes: [(page name, lines)] of the pages that changed."""
    out = ['# Changes since the previous report', '',
           f'{measured} page(s) measured, {len(changes)} changed. Blocks are matched by persistent identity, then signature, '
           'then by line of the source, then by tag and kind.', '']
    for name, lines in changes:
        out += [f'## {name}', ''] + lines + ['']
    return '\n'.join(out) + '\n'


def summary_markdown(rows, norms=None, design=None):
    """rows: (name, report path, analysis) in deck order; design: path of the
    reference of the design (macros and tokens), relative to the summary."""
    lines = [SUMMARY_HEADER]
    if design:
        lines.append(f'Macros, layouts and tokens of the design (use them instead of inline styles): '
                     f'`{design}`. Procedure for editing the slides: '
                     f'`{os.path.join(os.path.dirname(design), "agents.md")}`.\n')
    if norms:
        lines.append(norms_markdown(norms))
    debt = sum(len(r[2].get('lint', [])) for r in rows)
    if debt:
        lines.append(f"Values written by hand (design lint, column `lint`): {debt} in "
                     f"{sum(1 for r in rows if r[2].get('lint'))} of {len(rows)} pages; each page report "
                     f"gives the layout or macro that replaces them.\n")
    design_findings = [d for _, _, a in rows for d in a.get('role_design', [])]
    if design_findings:
        counts = {}
        for finding in design_findings:
            key = finding['kind']
            counts[key] = counts.get(key, 0) + 1
        lines.append(f"Design by role: {len(design_findings)} warnings in "
                     f"{sum(bool(a.get('role_design')) for _, _, a in rows)} pages; "
                     + ', '.join(f"{key}: {value}" for key, value in sorted(counts.items()))
                     + '. These are configurable heuristics requiring render inspection.\n')
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
    validate_design_rules(options.get('design_rules', {}))
    return options


def _run_node(script, arguments, label=None):
    """Run a Node script of assets/; its lines 'progress <done> <total> <item>'
    on stdout are shown as a progress bar (`label`). Returns its stderr."""
    cmd = ['node', script if os.path.isabs(script) else path_current_file + 'assets/' + script] + arguments
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        raise RuntimeError('node not found: install Node.js, then run `npm install` '
                           'in the static_website_lhtml directory')
    errors = []
    reader = threading.Thread(target=lambda: errors.extend(proc.stderr))   # no deadlock on a full pipe
    reader.start()
    with Progress(TextColumn('        {task.description}'), BarColumn(bar_width=24), MofNCompleteColumn(),
                  TimeRemainingColumn(),
                  TextColumn('{task.fields[item]}', table_column=Column(max_width=40, no_wrap=True,
                                                                         overflow='ellipsis')),
                  transient=True,
                  disable=label is None) as progress:
        task = progress.add_task(label or '', total=None, item='')
        for line in proc.stdout:
            parts = line.rstrip('\n').split(' ', 3)
            if parts[0] == 'progress' and len(parts) == 4:
                progress.update(task, completed=int(parts[1]), total=int(parts[2]),
                                item=parts[3].removesuffix('/index.html'))
    proc.wait()
    reader.join()
    stderr = ''.join(errors)
    if 'Cannot find module' in stderr:
        raise RuntimeError('puppeteer not found: run `npm install` in the static_website_lhtml directory')
    if proc.returncode:
        raise RuntimeError(f'{script} failed ({proc.returncode}): {stderr.strip()}')
    return stderr


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
        stderr = _run_node('layout_contact.js', [f'--input={sheets_json}'], label='Contact sheets')
        for line in stderr.splitlines():
            if line.startswith('layout_contact:'):
                log.error(line)
    finally:
        os.remove(sheets_json)


def _same_source(report, page, meta):
    """Whether the report of a page (layout.json) was made from its source: the
    pages of a deck that changed may now have the path of another one."""
    try:
        with open(report, encoding='utf-8') as fid:
            source = json.load(fid).get('source')
    except (OSError, ValueError):
        return False
    return source == os.path.relpath(page['source'], meta.get('config_directory') or '.')


def post_process(meta):
    # one build at a time writes the reports (another build waits for it)
    with report_lock(layout_output_directory(meta), meta['log']):
        return _post_process(meta)


def _post_process(meta):
    options = _options(meta)
    verification = None
    if meta.get('verify'):                      # agent extension (agent/README.md)
        from agent import report as agent_report
        options = agent_report.options(options)
    meta.setdefault('dependency_contexts', {})
    log = meta['log']
    site_dir = meta['site_directory']
    output_dir = str(layout_output_directory(meta))
    # --only: the pages built (or, when the pages of the site changed, the full
    # build measures only the pages named); the others keep their report
    requested = meta.get('measure')
    built = set(requested) if requested else {entry['dir'] + entry['filename'] for entry in built_pages(meta)}
    partial = len(built) < len(structure(meta))
    entries = {}

    pages, previous = [], []
    for entry in structure(meta):
        relative = entry['dir'] + entry['filename']
        if os.path.isabs(relative) or '..' in relative.replace('\\', '/').split('/'):
            raise ValueError(f'Invalid page path in layout structure: {relative}')
        entries[relative] = entry
        html = site_dir + relative
        page = {'html': os.path.abspath(html),
                'out': os.path.abspath(os.path.join(output_dir, 'pages', entry['dir'], entry['filename'])),
                'name': relative, 'source': entry['src'], 'layout': entry.get('layout')}
        if relative not in built:
            report = os.path.join(page['out'], 'layout.json')
            if partial and os.path.isfile(report) and (not requested or _same_source(report, page, meta)):
                previous.append(page)
            elif requested and os.path.isfile(html):       # its report is missing or of another page
                pages.append(page)
        elif os.path.isfile(html):
            pages.append(page)

    previous_layouts = {}             # the previous measure of the pages measured again, for changes.md
    for p in pages:
        path = os.path.join(p['out'], 'layout.json')
        if os.path.isfile(path) and requested and not _same_source(path, p, meta):
            os.remove(path)             # the report of another page (the deck changed): no changes
        elif os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fid:
                    previous_layouts[p['name']] = json.load(fid)
            except (OSError, ValueError):
                pass
            os.remove(path)             # a page whose measure fails has none (not the previous one)
    if os.path.isdir(output_dir) and not partial:
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    if not meta.get('verify'):              # aggregates of a previous --verify: no longer valid
        for name in ('verification.json', 'triage.json', 'triage.md'):
            if os.path.isfile(os.path.join(output_dir, name)):
                os.remove(os.path.join(output_dir, name))

    if requested:
        log.keyvalue('info', f'--only: {len(pages)} page(s) measured; the pages of the site changed, '
                             f'the others keep their report (--layout for all)', indent_level=2)
    log.keyvalue('*', f'Measure layout of {len(pages)} pages ...', indent_level=2)
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fid:
        json.dump([{'html': p['html'], 'out': p['out'], 'name': p['name'],
                    **(agent_report.page_entry(options, p['name']) if meta.get('verify') else {})}
                   for p in pages], fid)
        pages_json = fid.name
    try:
        stderr = _run_node('layout_measure.js', [
            f'--input={pages_json}', f"--root={options['root']}", f"--exclude={options['exclude']}",
            f"--width={options['width']}", f"--height={options['height']}",
            f"--images={1 if options['images'] else 0}"], label='Measure layout') if pages else ''
        for line in stderr.splitlines():
            if line.startswith('layout_measure:'):
                log.error(line)
    except RuntimeError as exc:
        if meta.get('verify'):
            agent_report.measurement_failed(pages, previous_layouts, output_dir, exc)
        raise
    finally:
        os.remove(pages_json)

    remeasured = {p['name'] for p in pages}
    measured = []
    for p in previous + pages:
        layout_path = os.path.join(p['out'], 'layout.json')
        if os.path.isfile(layout_path):
            with open(layout_path, encoding='utf-8') as fid:
                measured.append((p, layout_path, json.load(fid)))
    norms = deck_norms([layout for _, _, layout in measured])
    limits = {k: options[k] for k in ('max_words', 'min_font')}
    if meta.get('verify'):
        verification = agent_report.Verification(meta, options, output_dir, analyse, page_markdown,
                                                 count_problems, count_warnings, _run_node)

    rows = []
    loaded_design = meta.get('loaded_design')
    linter = Linter(loaded_design) if loaded_design else None
    order = {entry['dir'] + entry['filename']: k for k, entry in enumerate(structure(meta))}
    measured.sort(key=lambda m: order[m[0]['name']])
    for p, layout_path, layout in measured:
        entry = entries[p['name']]
        if p['name'] not in remeasured:         # retained measure: its validity is refreshed, not its geometry
            layout['freshness'] = dependencies.freshness(layout.get('dependencies'), meta, entry)
            with open(layout_path, 'w') as fid:
                json.dump(layout, fid, indent=1)
            with open(os.path.join(p['out'], 'layout.md'), 'w', encoding='utf-8', errors='replace') as fid:
                fid.write(page_markdown(p['name'], layout['source'], layout))
            if verification:
                verification.retained(p, layout)
            rows.append((p['name'], os.path.relpath(os.path.join(p['out'], 'layout.md'), output_dir),
                         layout['analysis']))
            continue
        analyse(layout, options['threshold'], norms, limits, options.get('design_rules'))
        if p['source'] in (meta.get('lint_findings') or {}):       # lint of the build
            layout['analysis']['lint'] = meta['lint_findings'][p['source']]
        elif linter is not None and os.path.isfile(p['source']):
            layout['analysis']['lint'] = [f.as_dict() for f in linter.lint_file(p['source'], p['layout'])]
        layout['source'] = os.path.relpath(p['source'], meta.get('config_directory') or '.')
        # the files the page depends on, to know whether a retained report is still valid
        meta.setdefault('runtime_resources', {})[p['name']] = layout.get('resources', [])
        layout['dependencies'] = dependencies.make_manifest(meta, entry, layout.get('resources', []))
        layout['freshness'] = dependencies.freshness(layout['dependencies'], meta, entry)
        if verification:
            verification.prepare(p, layout, previous_layouts.get(p['name']), limits)
        with open(layout_path, 'w') as fid:
            json.dump(layout, fid, indent=1)
        with open(os.path.join(p['out'], 'layout.md'), 'w', encoding='utf-8', errors='replace') as fid:
            fid.write(page_markdown(p['name'], layout['source'], layout))
        rows.append((p['name'], os.path.relpath(os.path.join(p['out'], 'layout.md'), output_dir),
                     layout['analysis']))
        if verification:
            verification.measured(p, layout, previous_layouts.get(p['name']))

    with open(os.path.join(output_dir, 'summary.md'), 'w', encoding='utf-8', errors='replace') as fid:
        reference = os.path.join(meta.get('published_site_directory') or site_dir, 'structure', 'design.md')
        fid.write(summary_markdown(rows, norms, design=os.path.relpath(reference, output_dir)
                                   if loaded_design and any(loaded_design.values()) else None))
    changes = [(p['name'], lines) for p, _, layout in measured if p['name'] in remeasured
               and p['name'] in previous_layouts
               and (lines := layout_changes(previous_layouts[p['name']], layout))]
    with open(os.path.join(output_dir, 'changes.md'), 'w', encoding='utf-8') as fid:
        fid.write(changes_markdown(changes, len(pages)))
    with open(os.path.join(output_dir, 'deck.json'), 'w') as fid:
        json.dump(norms, fid, indent=1)
    if options['images'] and measured:
        write_contact_sheets(output_dir, [(p['name'], os.path.relpath(p['out'], output_dir), layout['analysis'])
                                          for p, _, layout in measured],
                             measured[0][2]['viewport'], options, log,
                             changed={k for k, (p, _, _) in enumerate(measured) if p['name'] in remeasured}
                             if partial and not requested else None)      # deck changed: all the sheets
    if verification:
        verification.finish(pages, previous, stderr)

    n_problems = sum(count_problems(r[2]) for r in rows)
    if previous_layouts:
        log.keyvalue('info', f"Layout changes: {len(changes)} page(s) changed -> "
                             f"{os.path.relpath(os.path.join(output_dir, 'changes.md'))}", indent_level=2)
    log.keyvalue('info', f"Layout report: {len(pages)} measured, {len(rows)} pages, {n_problems} problems -> "
                         f"{os.path.relpath(os.path.join(output_dir, 'summary.md'))}", indent_level=2)
    if len(rows) < len(pages) + len(previous):
        raise RuntimeError(f'layout measurement failed for {len(pages) + len(previous) - len(rows)} page(s)')
