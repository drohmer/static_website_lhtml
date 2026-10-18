"""What the analysis found, as records of one shape.

Every check of lhtml_site/layout/analysis.py measures its own thing and returns its
own kind of row - one shape per check, whose only common field is `id`. This module is
the one place that turns them into findings:

    {key, code, severity, blocks, subject, detail, text, data}

`key` is the name of the check in the analysis, `code` what the report
prints (`HIDDEN TEXT`), `severity` one of SEVERITIES, `blocks` the ids the
finding is about (so the report can say where they are written, and so two
builds can be compared without reading prose), `text` the Markdown line
without its dash, and `data` the row the check produced.

Severity lives here, in the data, and not in two tuples of key names read by
two counting functions. The Markdown is rendered from these records, and
`changes.md` compares `code` and `blocks` instead of parsing sentences back
out of the rendered line.
"""
SEVERITIES = ('problem', 'warning', 'deviation', 'note')


def _zone(o):
    return f"x {o['x0']}..{o['x1']}, y {o['y0']}..{o['y1']}"


def _direction(n):
    if n['axis'] == 'x':
        return 'right of' if n['delta'] > 0 else 'left of'
    return 'below' if n['delta'] > 0 else 'above'


def _line_item(tag):
    """What a wrapped line of text is, for the sentence of a finding."""
    if tag[0] == 'h':
        return 'title'
    return {'credit': 'credit', 'ref': 'reference'}.get(tag.split('.')[-1], 'paragraph' if tag == 'p' else 'list item')


def _ids(*values):
    return ' × '.join(f'#{v}' for v in values)


# One builder per check: a row of the analysis in, (code, blocks, subject,
# detail) out. The subject is what follows the code on the line, usually the
# blocks; the detail what follows the colon.

def _hidden_text(h):
    return ('HIDDEN TEXT', [h['id'], h['by']], f"#{h['id']} under #{h['by']}",
            f"{_zone(h)} ({round(100 * h['fraction'])} % of the text of #{h['id']} is covered)")


def _collision(c):
    return 'COLLISION', [c['a'], c['b']], _ids(c['a'], c['b']), f"{_zone(c)} ({c['area']} px² of drawn content)"


def _out_of_area(o):
    return ('OUT OF AREA', [o['id']], f"#{o['id']}",
            ', '.join(f'{v} px {k}' for k, v in o.items() if k != 'id'))


def _clipped(c):
    return ('CLIPPED', [c['id']], f"#{c['id']}",
            f"{c['w']} px (width) / {c['h']} px (height) of content hidden")


def _upscaled(u):
    return 'UPSCALED IMAGE', [u['id']], f"#{u['id']}", f"{u['src']} displayed at ×{u['scale']} (blurry)"


def _reserved(r):
    return ('RESERVED AREA', [r['id']], f"#{r['id']}",
            f"text over the {r['name']} of the theme ({_zone(r)})")


def _collapsed(c):
    return ('COLLAPSED FIGURE', [c['id']], f"#{c['id']}",
            f"{c['src']} drawn at {c['w']} × {c['h']} px (invisible)")


def _svg_overflow(o):
    sides = ', '.join(f'{o[k]} px {k}' for k in ('left', 'top', 'right', 'bottom') if o.get(k, 0) > 0)
    return ('SVG OVERFLOW', [o['id']], f"#{o['id']}",
            f"{o['src']} draws beyond its viewBox ({sides}): cut when shown")


def _internal_collision(c):
    return 'INTERNAL COLLISION', [c['a'], c['b']], _ids(c['a'], c['b']), _zone(c)


def _internal_clipped(c):
    return 'INTERNAL CLIPPED', [c['id']], f"#{c['id']}", f"{c['w']} px width / {c['h']} px height"


def _internal_overflow(c):
    return ('COLUMN OVERFLOW', [c['id'], c['parent']], f"#{c['id']} outside #{c['parent']}",
            ', '.join(f"{c[k]} px {k}" for k in ('left', 'right') if k in c))


def _tight(t):
    return ('TIGHT', [t['a'], t['b']], _ids(t['a'], t['b']),
            f"line box of text overlapping by {t['y1'] - t['y0']} px ({_zone(t)}); "
            f"the glyphs probably do not touch, but the spacing is tight")


def _internal_tight(t):
    return 'INTERNAL TIGHT', [t['a'], t['b']], _ids(t['a'], t['b']), f"{_zone(t)}; inspect text spacing"


def _near_aligned(n):
    return ('NEAR-ALIGNED', [n['id']], f"#{n['id']}",
            f"{n['edge']} at {n['axis']} {n['value']}, {abs(n['delta'])} px {_direction(n)} "
            f"the {n['ref_label']} ({n['axis']} {n['ref']})")


def _wrapped(w):
    what = _line_item(w['tag'])
    tail = '' if what == 'title' else f", the last one {w['last_w']} px wide (first {w['first_w']} px)"
    return 'WRAPPED', [w['id']], f"#{w['id']}", f"{what} \"{w['text']}\" on {w['lines']} lines{tail}"


def _short_wrapped(w):
    return ('SHORT WRAPPED', [w['id']], f"#{w['id']}",
            f"{_line_item(w['tag'])} \"{w['text']}\" on {w['lines']} lines, {w['natural_w']} px on one line "
            f"for {w['avail_w']} px available (+{w['missing']} px); it would fit on one line of the slide")


def _row(r):
    values = ', '.join(f'{f} {v}' for f, v in zip(r['figures'], r['values']))
    return ('ROW', [r['id']], f"#{r['id']}",
            f"the {r['edge']}s of the figures side by side differ by {r['spread']} px ({values})")


def _fit(f):
    cropped = f['kind'] == 'cropped'
    return ('CROPPED' if cropped else 'SMALL IN ITS BOX', [f['id']], f"#{f['id']}",
            f"{f['src']} " + (f"{round(100 * f['part'])} % cut ({f['sides']})" if cropped else
                              f"drawn on {round(100 * f['part'])} % of its box (empty {f['sides']})"))


def _svg_label(f):
    texts = ', '.join(f'"{t}"' for t in f['texts'])
    if f['count'] > len(f['texts']):
        texts += f" and {f['count'] - len(f['texts'])} more"
    return ('SVG LABEL', [f['id']], f"#{f['id']}",
            f"in {f['src']}, {texts} {'is' if f['count'] == 1 else 'are'} drawn across a {f['over']} "
            f"(move it, or give it a halo: paint-order=\"stroke\" stroke=\"white\")")


def _dense(d):
    what = {'words': 'words of text', 'min_font': 'px: smallest font size'}[d['kind']]
    limit = 'minimum' if d['kind'] == 'min_font' else 'limit'
    return ('SMALL FONT' if d['kind'] == 'min_font' else 'DENSE', [], None,
            f"{d['value']} {what} ({limit} {d['limit']})")


def _role_design(d):
    return ('DESIGN', [d['id']], f"{d['kind']} #{d['id']} ({d['role']})",
            f"{d['value']} vs {d['limit']}; {d['advice']}")


def _canvas_overlap(d):
    return 'CANVAS OVERLAP', [], _zone(d), d['reason']


def _deviation(d):
    if d['kind'] == 'title_position':
        return ('TITLE POSITION', [d['id']], f"#{d['id']}",
                f"{d['anchor'][0]} x {d['value'][0]}, {d['anchor'][1]} y {d['value'][1]}; "
                f"usual {d['norm'][0]}, {d['norm'][1]}")
    if d['kind'] == 'title_variant':
        return 'TITLE VARIANT', [d['id']], f"#{d['id']}", f"{d['value']}; usual page titles: {d['norm']}"
    if d['kind'] == 'title_gap':
        return 'TITLE GAP', [d['id']], f"#{d['id']}", f"{d['value']} px below the title; usual {d['norm']} px"
    return ('TEXT FONT', [d['id']], f"#{d['id']}",
            f"text at {d['value']} px; usual text sizes {', '.join(map(str, d['norm']))} px")


def _intentional(c):
    return ('INTENTIONAL OVERLAP', [c['a'], c['b']], _ids(c['a'], c['b']),
            f"{_zone(c)}; marked as intentional (class overlay)")


def _background_overlap(o):
    return ('BACKGROUND OVERLAP', [o['other'], o['image']], f"#{o['other']} over #{o['image']}",
            f"only the background (uniform or transparent) of image {o['src']} is under it: "
            f"not visible, but the image box is reserved there")


# The checks in the order the report prints them. Adding a check means adding
# one line here and one builder above; nothing else knows the list.
CHECKS = (
    ('hidden_text', 'problem', _hidden_text),
    ('collisions', 'problem', _collision),
    ('out_of_area', 'problem', _out_of_area),
    ('clipped', 'problem', _clipped),
    ('upscaled_images', 'problem', _upscaled),
    ('reserved', 'problem', _reserved),
    ('collapsed', 'problem', _collapsed),
    ('svg_overflow', 'problem', _svg_overflow),
    ('internal_collisions', 'problem', _internal_collision),
    ('internal_clipped', 'problem', _internal_clipped),
    ('internal_overflow', 'problem', _internal_overflow),
    ('tight', 'warning', _tight),
    ('internal_tight', 'warning', _internal_tight),
    ('near_aligned', 'warning', _near_aligned),
    ('wrapped', 'warning', _wrapped),
    ('short_wrapped', 'warning', _short_wrapped),
    ('rows', 'warning', _row),
    ('fit', 'warning', _fit),
    ('svg_labels', 'warning', _svg_label),
    ('dense', 'warning', _dense),
    ('role_design', 'warning', _role_design),
    ('canvas_overlaps', 'warning', _canvas_overlap),
    ('deviations', 'deviation', _deviation),
    ('intentional', 'note', _intentional),
    ('background_overlaps', 'note', _background_overlap),
)


def findings(analysis):
    """Every finding of an analysis, in the order the report prints them.

    analyse() records the list in analysis['findings'], and it is the list
    that is returned when it is there: a report written from a build read
    back from disk says what that build found, not what today's code would
    make of its rows."""
    if 'findings' in analysis:
        return analysis['findings']
    result = []
    for key, severity, build in CHECKS:
        for row in analysis.get(key) or []:
            code, blocks, subject, detail = build(row)
            result.append({'key': key, 'code': code, 'severity': severity, 'blocks': blocks,
                           'subject': subject, 'detail': detail,
                           'text': f"{code} {subject}: {detail}" if subject else f"{code}: {detail}",
                           'data': row})
    return result


def count(analysis, severity):
    """How many findings of that severity an analysis holds."""
    return sum(1 for f in findings(analysis) if f['severity'] == severity)


def count_problems(analysis):
    return count(analysis, 'problem')


def count_warnings(analysis):
    return count(analysis, 'warning')
