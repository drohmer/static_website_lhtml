"""What a measured page shows, judged: collisions, overflows, clipped and
hidden content, density, alignment, and the deviations from the usual values
of the deck.

Every function here reads measurements and returns findings. None of them
touches the file system, the configuration or the build: a layout.json is
enough to run them, which is what makes them testable one by one
(tests/test_layout_report.py).

Coordinates are in CSS pixels, origin at the top-left corner of the page.
"""
from lib.design_checks import analyse_design

FLOW_POSITIONS = ('static', 'relative', 'sticky')


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


def _overlay(block):
    """A block laid over the content rather than placed in it: marked as an
    intentional overlay (class 'overlay'), or fixed to the viewport. A
    timer, a page number, a watermark or a full-bleed figure is positioned
    against the page on purpose, so the margins the content keeps do not
    apply to it."""
    return bool(block.get('intentional')) or block.get('position') == 'fixed'


def find_out_of_area(blocks, area, threshold=4, scrolling=False, page=None):
    """Blocks extending beyond the usable area: {id, left, top, right, bottom} in px.
    On a scrolling page (web page, not a slide), the bottom side is not checked.
    An overlay (_overlay) is compared with the whole page when it is known:
    it covers the slide, or sits in its margin, on purpose - while one that
    spills past the page itself is still reported."""
    result = []
    for b in blocks:
        bounds = page if page and _overlay(b) else area
        ax0, ay0 = bounds['x'], bounds['y']
        ax1, ay1 = bounds['x'] + bounds['w'], bounds['y'] + bounds['h']
        x0, y0, x1, y1 = _rect(b)
        out = {'left': ax0 - x0, 'top': ay0 - y0, 'right': x1 - ax1, 'bottom': y1 - ay1}
        out = {k: v for k, v in out.items() if v > threshold and not (scrolling and k == 'bottom')}
        if out:
            result.append({'id': b['id'], **out})
    return result


def _page_rect(layout):
    """The whole page, for the blocks an intentional overlay covers on
    purpose; None when the measurement does not say its size."""
    viewport = layout.get('viewport')
    return {'x': 0, 'y': 0, 'w': viewport['w'], 'h': viewport['h']} if viewport else None


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
    navigation): {id, name, x0, y0, x1, y1}. An element of the theme is
    measured as one rectangle per part that paints, so a block covering a
    navigation of several parts is reported once, over all of them, and not
    once per part.

    Only text counts: the navigation of a theme is drawn over the content,
    so a figure or a background passing under it is what a full-bleed slide
    is for, while a text written there is unreadable."""
    covered = {}
    for zone in reserved or []:
        z = (zone['x'], zone['y'], zone['x'] + zone['w'], zone['y'] + zone['h'])
        for b in blocks:
            parts = [o for r in _ink(b) if r[4] == 'text' and (o := _overlap(r, z, threshold))]
            if parts:
                covered.setdefault((b['id'], zone.get('name', 'reserved')), []).extend(parts)
    found = []
    for (block_id, name), parts in covered.items():
        bounds = _bounds(parts)
        found.append({'id': block_id, 'name': name,
                      **{k: bounds[k] for k in ('x0', 'y0', 'x1', 'y1')}})
    return sorted(found, key=lambda f: (f['id'], f['name']))


def find_wrapped(blocks, short=0.3):
    """Titles written on several lines, and list items, paragraphs, credits or
    references whose last line holds only a few words (shorter than `short` ×
    the first line)."""
    found = []
    for b in blocks:
        for w in b.get('wrapped', []):
            if _orphan(w, short):
                found.append({'id': b['id'], **w})
    return found


def _orphan(w, short=0.3):
    return w['tag'][0] == 'h' or (w['lines'] == 2 and w['last_w'] < short * w['first_w'])


def _line_item(tag):
    if tag[0] == 'h':
        return 'title'
    return {'credit': 'credit', 'ref': 'reference'}.get(tag.split('.')[-1], 'paragraph' if tag == 'p' else 'list item')


def find_short_wrapped(blocks, area, short=0.3, tolerance=4):
    """Text written on several lines that would fit on one line of the slide:
    its width on one line is at most the width from its left edge to the right
    of the area. Titles and the items already reported by find_wrapped are left
    out, and so are lines broken in the source (<br>: no width is missing);
    `missing` is the width the element lacks to hold it on one line."""
    found = []
    right = area['x'] + area['w']
    for b in blocks:
        for w in b.get('wrapped', []):
            if 'natural_w' not in w or _orphan(w, short):
                continue
            missing = w['natural_w'] - w['avail_w']
            if missing > tolerance and w['natural_w'] <= right - w['x']:
                found.append({'id': b['id'], **w, 'missing': missing})
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
    axis: {id, axis, edge, value, ref, ref_label, delta}.
    An overlay (_overlay) is left out on both sides: it is positioned against
    the page, not in the grid of the content, so neither is it misaligned with
    the content nor is the content misaligned with it."""
    blocks = [b for b in blocks if not _overlay(b)]
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
    # On a scrolling page the window is not the page: measuring how much of
    # it is covered over one window height counts the first screenful and
    # calls it the page. The content that exists is the area to measure, and
    # the space left under the last block - a question about a slide - has
    # none: a page continues.
    scrolling = layout.get('scrolling', False)
    covered_area = dict(area, h=max(area['h'], bottom - area['y'])) if scrolling else area
    collisions, tight, intentional = find_overlaps(blocks, threshold)
    hidden_text = find_hidden_text(blocks)
    # a collision between a text and the block hiding it is reported once, as hidden text
    hiding = {frozenset((h['id'], h['by'])) for h in hidden_text}
    collisions = [c for c in collisions if frozenset((c['a'], c['b'])) not in hiding]
    grid = coverage(_ink_rects(blocks), covered_area)   # occupancy, then free area (with the reserved areas)
    covered = _covered_share(grid)
    coverage(_reserved_rects(layout.get('reserved')), covered_area, rows=grid)
    layout['analysis'] = {
        'reserved': find_reserved_overlaps(blocks, layout.get('reserved'), threshold),
        'collisions': collisions,
        'hidden_text': hidden_text,
        'out_of_area': find_out_of_area(blocks, area, threshold, layout.get('scrolling', False),
                                       page=_page_rect(layout)),
        'clipped': find_clipped(blocks, threshold),
        'upscaled_images': find_upscaled_images(blocks),
        'collapsed': find_collapsed(blocks),
        'svg_overflow': find_svg_overflow(blocks, threshold),
        'svg_labels': find_svg_labels(blocks),
        'tight': tight,
        'intentional': intentional,
        'background_overlaps': find_background_overlaps(blocks, collisions + intentional, threshold),
        'gaps': vertical_gaps(blocks),  # spacers count as gaps
        # what occupancy, density and 'free' are measured over: the usable
        # area, or, on a page that scrolls, the content it holds
        'measured_height': covered_area['h'],
        'free_bottom': None if scrolling else area['y'] + area['h'] - bottom,
        'occupancy': round(covered, 2),
        'near_aligned': find_near_alignments(blocks, area, norms.get('columns', ())),
        'density': density(blocks, covered_area),
        'wrapped': find_wrapped(blocks),
        'short_wrapped': find_short_wrapped(blocks, area),
        'rows': find_row_misalignments(blocks),
        'fit': find_fit(blocks),
        'free': _free_rect(grid, covered_area),
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


WARNING_KEYS = ('tight', 'near_aligned', 'dense', 'wrapped', 'short_wrapped', 'rows', 'fit', 'svg_labels', 'internal_tight', 'role_design', 'canvas_overlaps')


def count_problems(analysis):
    return sum(len(analysis.get(k, [])) for k in PROBLEM_KEYS) + analysis.get('nested_problems', 0)


def count_warnings(analysis):
    return sum(len(analysis.get(k, [])) for k in WARNING_KEYS) + analysis.get('nested_warnings', 0)
