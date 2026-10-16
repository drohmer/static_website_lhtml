"""The report written from an analysis: layout.md of a page, summary.md of
the deck, changes.md between two builds, and the HTML of the contact sheets.

Text in, text out: nothing here writes a file (lib/layout/measure.py does).
"""
import posixpath

from lib.layout.analysis import _rect
from lib.layout.findings import count_problems, count_warnings, findings


def _md_cell(text):
    return str(text).replace('|', '\\|').replace('\n', ' ')


def where(source, page_source, near=False):
    """Where a block is written, as a reader of the report needs it: the line
    alone when it is the source of the page (named in the header), the file
    and the line when it comes from another one, and said plainly when the
    block carries no marker - a block written by a script has none, and a
    silent dash would read as a block nobody can find.

    `near`: the line is a landmark, not the position of the block. The
    build marks the lines of the page it renders, and nothing else: a block
    that comes from an included file, or that holds the marker of a block
    inside it, takes the line of what is around it. Saying 'line 11' there
    sends a reader to another block, so it says 'near line 11'."""
    if not source:
        return 'no source marker'
    file, _, line = source.rpartition(':')
    place = f'line {line}' if file == page_source else source
    return f'near {place}' if near else place


def located(finding, sources=None, page_source=None):
    """A finding as a line of Markdown, followed by where the blocks it
    names are written. `sources`: {block id: (source, near)}."""
    line = '- ' + finding['text']
    places = dict.fromkeys(str(b) for b in finding['blocks'])
    if not places or sources is None:
        return line
    for ident in places:
        source, near = sources.get(ident) or (None, False)
        places[ident] = where(source, page_source, near)
    shown = [f'#{i} {place}' for i, place in places.items()] if len(places) > 1 \
        else list(places.values())
    return f"{line} [{', '.join(shown)}]"


def problem_lines(analysis, sources=None, page_source=None):
    """The problems of a page, one Markdown line each."""
    return [located(f, sources, page_source) for f in findings(analysis)
            if f['severity'] == 'problem']


def _line_cell(block, page_source):
    """The `line` column of a block: its line in the page, `~n` when that
    line is a landmark (see `where`), `file:n` when the block is written in
    another file than the page, and `-` when nothing names it. Without the
    file, a block of an included file shows a line number a reader takes
    for a line of the page."""
    line = block.get('line')
    if not line:
        return '-'
    file, _, _ = (block.get('source') or '').rpartition(':')
    place = str(line) if file in ('', page_source) else f'{file}:{line}'
    return f'~{place}' if block.get('source_near') else place


def page_markdown(name, source, layout):
    """Markdown report of one page."""
    area, analysis = layout['area'], layout['analysis']
    lines = [f'# {name}', '',
             f'Source: `{source}`', '',
             f"Usable area: x {area['x']}..{area['x'] + area['w']}, y {area['y']}..{area['y'] + area['h']} "
             f"({area['w']}×{area['h']} px) · occupancy {round(100 * analysis['occupancy'])} %"
             + (f" · free space at the bottom {analysis['free_bottom']} px"
                if analysis['free_bottom'] is not None else
                f" · scrolling page: occupancy and free space measured over its content, "
                f"y {area['y']}..{area['y'] + analysis.get('measured_height', area['h'])}"), '',
             'Positions and sizes bound the ink of each block: what is actually drawn '
             '(text lines, images reduced to their drawn shape, backgrounds, borders). '
             'Overlaps are computed on the ink rectangles themselves (layout.json: "ink"), '
             'so the empty corners of a block do not count. Spacers are empty blocks.', '',
             'Line: line of the source where the block starts; `file:n` when the block is '
             'written in another file than the page; `~n`, the line of what is around it, when '
             'the block itself is not marked; `-` when nothing marks it (a block a script '
             'writes). Each finding below ends with where its blocks are written, in the same '
             'forms.', '',
             '| # | line | kind | x, y | w × h | margins (t r b l) | position | font | signature |',
             '|---|------|------|------|-------|-------------------|----------|------|-----------|']
    for b in layout['blocks']:
        x0, y0, x1, y1 = _rect(b)
        kind = b['kind'] + (' (overlay)' if b.get('intentional') else '') \
            + (f" in #{b['inside']}" if b.get('inside') else '')
        line_cell = _line_cell(b, source)
        lines.append(f"| {b['id']} | {line_cell} | {kind} | {x0}, {y0} | {x1 - x0} × {y1 - y0} | "
                     f"{' '.join(str(m) for m in b['margin'])} | {b['position']} | {b['font_size']} | "
                     f"{_md_cell(b['signature'])} |")

    # Where each block is written: the findings carry it, so that a page is
    # opened at the line instead of being searched for a signature.
    sources = {str(b['id']): (b.get('source'), bool(b.get('source_near')))
               for b in layout.get('blocks', []) + layout.get('subblocks', [])}
    by_severity = {}
    for finding in findings(analysis):
        by_severity.setdefault(finding['severity'], []).append(located(finding, sources, source))

    lines += ['', '## Problems', ''] + (by_severity.get('problem') or ['None.'])
    for severity, heading in (('warning', 'Warnings'),
                              ('deviation', 'Differences with the rest of the deck'),
                              ('note', 'Notes')):
        if by_severity.get(severity):
            lines += ['', '## ' + heading, ''] + by_severity[severity]

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
                  'Replace them with the layout or macro given (see .structure/design.md):', '']
        lines += [f"- line {f['line']}, {f['kind']}: `{f['text']}` -> {f['advice']}" for f in analysis['lint']]

    if analysis['gaps']:
        lines += ['', '## Vertical gaps between in-flow blocks', '',
                  ', '.join(f'#{a}→#{b}: {g} px' for a, b, g in analysis['gaps'])]
    if layout.get('freshness'):
        lines += ['', '## Report validity', '', 'Freshness: **' + layout['freshness']['status'] + '**.']
        for change in layout['freshness'].get('changes', []):
            lines.append(f"- {change['kind']}: {change.get('path') or 'page parameters or metadata'}")
    return '\n'.join(lines) + '\n'


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
(bitmap displayed larger than its native size: blurry), RESERVED AREA (text
written over the navigation of the theme), COLLAPSED FIGURE (image or video drawn
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
several lines, or list item with a few words on its second line), SHORT
WRAPPED (text on several lines that would fit on one line of the slide: give
it the missing width, or shorten it), ROW (figures
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
    """{(code, signatures of its blocks): [text]} of the problems of a measure.
    The ids of the blocks change from a measure to the next, their signature
    does not, so identical blocks share a key: one entry each. The finding
    gives its code and its blocks, so a change of wording does not change
    what two builds are compared on."""
    signature = {b['id']: b['signature'] for b in layout.get('blocks', [])}
    found = {}
    for finding in findings(layout.get('analysis') or {}):
        if finding['severity'] != 'problem':
            continue
        key = (finding['code'], tuple(signature.get(i) for i in finding['blocks']))
        found.setdefault(key, []).append(finding['text'])
    return found


def layout_changes(old, new, threshold=4):
    """What changed between two measures of a page: problems that appeared or
    were solved, counts of warnings and lint, blocks moved or resized (matched
    by signature), blocks added or removed. Returns lines of Markdown (none:
    no change)."""
    lines = []
    a, b = old.get('analysis', {}), new.get('analysis', {})
    before, after = _problems_by_key(old), _problems_by_key(new)
    lines += [f'- new problem: {text}' for key, found in after.items() for text in found[len(before.get(key, [])):]]
    lines += [f'- solved: {text}' for key, found in before.items() for text in found[len(after.get(key, [])):]]
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
                     f'`{posixpath.join(posixpath.dirname(design), "agents.md")}`.\n')
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
