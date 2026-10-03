"""Layout report: positions, collisions and overflows of the blocks of each page.

The layout is measured in headless Chrome (assets/layout_measure.js,
requires `npm install`), then analysed here. For each page, the report is
written to <config_dir>/_layout/<page dir>/:

    layout.md    blocks (position, size, signature) and detected problems
    layout.json  raw measurements and analysis
    overlay.png  real render with numbered block outlines
    blocks.png   one solid rectangle per block (content hidden)

and <config_dir>/_layout/summary.md lists all pages sorted by number of
problems. Coordinates are in CSS pixels, origin at the top-left corner of
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
        output: '_layout/'   # output directory, relative to the config directory
"""

import json
import os
import shutil
import subprocess
import tempfile

from lib.structure import load_structure


DEFAULTS = {'root': 'body', 'exclude': 'nav, footer', 'width': 1920, 'height': 1080, 'images': True,
            'threshold': 4, 'output': '_layout/'}

FLOW_POSITIONS = ('static', 'relative', 'sticky')

path_current_file = os.path.dirname(os.path.abspath(__file__)) + '/'


# ---------------------------------------------------------------------------
# Analysis (pure functions on the measured layout)
# ---------------------------------------------------------------------------

def _rect(block):
    """Ink extent of a block (what is drawn), or its layout box for spacers."""
    r = block.get('visual') or block['box']
    return r['x'], r['y'], r['x'] + r['w'], r['y'] + r['h']


def _visible(blocks):
    """Blocks that draw something (spacers excluded)."""
    return [b for b in blocks if b.get('kind') != 'spacer']


def find_collisions(blocks, threshold=4):
    """Pairs of blocks whose visual extents overlap by more than `threshold`
    pixels in both directions. Returns dicts (a, b, x0, y0, x1, y1)."""
    collisions = []
    for i, a in enumerate(blocks):
        ax0, ay0, ax1, ay1 = _rect(a)
        for b in blocks[i + 1:]:
            bx0, by0, bx1, by1 = _rect(b)
            x0, y0, x1, y1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
            if x1 - x0 > threshold and y1 - y0 > threshold:
                collisions.append({'a': a['id'], 'b': b['id'], 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1})
    return collisions


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


def find_upscaled_images(blocks, tolerance=1.05):
    """Images displayed larger than their native size (blurry): {id, src, scale}."""
    result = []
    for b in blocks:
        for m in b.get('media', []):
            if m.get('natural_w') and m['w'] > m['natural_w'] * tolerance:
                result.append({'id': b['id'], 'src': m['src'], 'scale': round(m['w'] / m['natural_w'], 2)})
    return result


def vertical_gaps(blocks):
    """Gaps between consecutive in-flow blocks, top to bottom: [(id_above, id_below, gap px)]."""
    flow = sorted((b for b in blocks if b.get('position') in FLOW_POSITIONS), key=lambda b: _rect(b)[1])
    return [(a['id'], b['id'], _rect(b)[1] - _rect(a)[3]) for a, b in zip(flow, flow[1:])]


def occupancy(blocks, area, step=10):
    """Fraction of the usable area covered by at least one block (sampled on a grid)."""
    if area['w'] <= 0 or area['h'] <= 0:
        return 0.0
    rects = [_rect(b) for b in blocks]
    covered = total = 0
    for y in range(area['y'] + step // 2, area['y'] + area['h'], step):
        for x in range(area['x'] + step // 2, area['x'] + area['w'], step):
            total += 1
            if any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in rects):
                covered += 1
    return covered / total if total else 0.0


def analyse(layout, threshold=4):
    """Add an 'analysis' entry to a measured layout and return it."""
    blocks, area = _visible(layout['blocks']), layout['area']
    bottom = max((_rect(b)[3] for b in blocks), default=area['y'])
    layout['analysis'] = {
        'collisions': find_collisions(blocks, threshold),
        'out_of_area': find_out_of_area(blocks, area, threshold, layout.get('scrolling', False)),
        'clipped': find_clipped(blocks, threshold),
        'upscaled_images': find_upscaled_images(blocks),
        'gaps': vertical_gaps(blocks),  # spacers count as gaps
        'free_bottom': area['y'] + area['h'] - bottom,
        'occupancy': round(occupancy(blocks, area), 2),
    }
    return layout['analysis']


def count_problems(analysis):
    return (len(analysis['collisions']) + len(analysis['out_of_area'])
            + len(analysis['clipped']) + len(analysis['upscaled_images']))


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def _md_cell(text):
    return str(text).replace('|', '\\|').replace('\n', ' ')


def page_markdown(name, source, layout):
    """Markdown report of one page."""
    area, analysis = layout['area'], layout['analysis']
    lines = [f'# {name}', '',
             f'Source: `{source}`', '',
             f"Usable area: x {area['x']}..{area['x'] + area['w']}, y {area['y']}..{area['y'] + area['h']} "
             f"({area['w']}×{area['h']} px) · occupancy {round(100 * analysis['occupancy'])} % "
             f"· free space at the bottom {analysis['free_bottom']} px", '',
             'Positions and sizes are the ink extent of each block (text, images, '
             'backgrounds and borders actually drawn); spacers are empty blocks.', '',
             '| # | kind | x, y | w × h | margins (t r b l) | position | font | signature |',
             '|---|------|------|-------|-------------------|----------|------|-----------|']
    for b in layout['blocks']:
        x0, y0, x1, y1 = _rect(b)
        lines.append(f"| {b['id']} | {b['kind']} | {x0}, {y0} | {x1 - x0} × {y1 - y0} | "
                     f"{' '.join(str(m) for m in b['margin'])} | {b['position']} | {b['font_size']} | "
                     f"{_md_cell(b['signature'])} |")

    problems = []
    for c in analysis['collisions']:
        problems.append(f"- COLLISION #{c['a']} × #{c['b']}: overlap x {c['x0']}..{c['x1']}, "
                        f"y {c['y0']}..{c['y1']} ({c['x1'] - c['x0']}×{c['y1'] - c['y0']} px)")
    for o in analysis['out_of_area']:
        sides = ', '.join(f'{v} px {k}' for k, v in o.items() if k != 'id')
        problems.append(f"- OUT OF AREA #{o['id']}: {sides}")
    for c in analysis['clipped']:
        problems.append(f"- CLIPPED #{c['id']}: {c['w']} px (width) / {c['h']} px (height) of content hidden")
    for u in analysis['upscaled_images']:
        problems.append(f"- UPSCALED IMAGE #{u['id']}: {u['src']} displayed at ×{u['scale']} (blurry)")
    lines += ['', '## Problems', ''] + (problems or ['None.'])

    if analysis['gaps']:
        lines += ['', '## Vertical gaps between in-flow blocks', '',
                  ', '.join(f'#{a}→#{b}: {g} px' for a, b, g in analysis['gaps'])]
    return '\n'.join(lines) + '\n'


SUMMARY_HEADER = '''# Layout summary

One section per page in `<page>/layout.md` (block table + problems), with
`<page>/overlay.png` (real render, numbered outlines) and `<page>/blocks.png`
(solid rectangles). Coordinates are CSS pixels, origin at the top-left corner
of the page; "usable area" is the inside of the slide frame. Block
numbers (#) match the images. A block is found in the source with its
signature (tag, inline style, beginning of text, image names).

Problems: COLLISION (blocks overlapping), OUT OF AREA (block beyond the
usable area), CLIPPED (content cut by overflow), UPSCALED IMAGE (blurry).
'''


def summary_markdown(rows):
    lines = [SUMMARY_HEADER,
             '| page | problems | collisions | out of area | clipped | upscaled | occupancy | report |',
             '|------|----------|------------|-------------|---------|----------|-----------|--------|']
    for name, report_path, a in sorted(rows, key=lambda r: (-count_problems(r[2]), r[0])):
        lines.append(f"| {name} | {count_problems(a)} | {len(a['collisions'])} | {len(a['out_of_area'])} | "
                     f"{len(a['clipped'])} | {len(a['upscaled_images'])} | {round(100 * a['occupancy'])} % | "
                     f"[layout.md]({report_path}) |")
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

def _options(meta):
    options = dict(DEFAULTS)
    options.update((meta.get('plugin_arg') or {}).get('layout_report') or {})
    return options


def post_process(meta):
    options = _options(meta)
    log = meta['log']
    site_dir = meta['site_directory']
    output_dir = os.path.join(meta.get('config_directory', ''), options['output'])
    structure = load_structure(site_dir)

    pages = []
    for entry in structure:
        html = site_dir + entry['dir'] + entry['filename']
        if os.path.isfile(html):
            pages.append({'html': os.path.abspath(html),
                          'out': os.path.abspath(os.path.join(output_dir, entry['dir'])),
                          'name': entry['dir'].rstrip('/') or entry['filename'],
                          'source': meta['source_directory'] + entry['dir']
                                    + entry['filename'].replace('.html', '.html.j2')})

    if os.path.isdir(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    log.keyvalue('*', f'Measure layout of {len(pages)} pages ...', indent_level=2)
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fid:
        json.dump([{'html': p['html'], 'out': p['out']} for p in pages], fid)
        pages_json = fid.name
    try:
        cmd = ['node', path_current_file + 'assets/layout_measure.js', f'--input={pages_json}',
               f"--root={options['root']}", f"--exclude={options['exclude']}", f"--width={options['width']}",
               f"--height={options['height']}", f"--images={1 if options['images'] else 0}"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            raise RuntimeError('node not found: install Node.js, then run `npm install` '
                               'in the static_website_lhtml directory')
        if 'Cannot find module' in proc.stderr:
            raise RuntimeError('puppeteer not found: run `npm install` in the static_website_lhtml directory')
        for line in proc.stderr.splitlines():
            if line.startswith('layout_measure:'):
                log.error(line)
    finally:
        os.remove(pages_json)

    rows = []
    for p in pages:
        layout_path = os.path.join(p['out'], 'layout.json')
        if not os.path.isfile(layout_path):
            continue
        with open(layout_path, encoding='utf-8') as fid:
            layout = json.load(fid)
        analyse(layout, options['threshold'])
        layout['source'] = os.path.relpath(p['source'], meta.get('config_directory') or '.')
        with open(layout_path, 'w') as fid:
            json.dump(layout, fid, indent=1)
        with open(os.path.join(p['out'], 'layout.md'), 'w', encoding='utf-8', errors='replace') as fid:
            fid.write(page_markdown(p['name'], layout['source'], layout))
        rows.append((p['name'], os.path.relpath(os.path.join(p['out'], 'layout.md'), output_dir),
                     layout['analysis']))

    with open(os.path.join(output_dir, 'summary.md'), 'w', encoding='utf-8', errors='replace') as fid:
        fid.write(summary_markdown(rows))

    n_problems = sum(count_problems(r[2]) for r in rows)
    log.keyvalue('info', f"Layout report: {len(rows)} pages, {n_problems} problems -> "
                         f"{os.path.relpath(os.path.join(output_dir, 'summary.md'))}", indent_level=2)
    if len(rows) < len(pages):
        raise RuntimeError(f'layout measurement failed for {len(pages) - len(rows)} page(s)')
