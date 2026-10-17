"""The layout analysis of a build: measure the pages of the site, write the
report, keep what a previous build measured.

Run by `--layout` (generate.py), after the pages are built and the themes
rendered. For each page, the report is written to <config_dir>/.layout/pages/
<relative HTML path>/:

    layout.md    blocks (position, size, signature), detected problems,
                 warnings, differences with the rest of the deck, density
    layout.json  raw measurements and analysis
    render.png   real render
    overlay.png  real render with numbered block outlines        (images: true)
    blocks.png   one solid rectangle per block (content hidden)   (images: true)
    internal-overlay.png  real render with the inner blocks outlined (images: true)

A page is measured again only when something it shows changed: its report
is kept when its HTML and every file it loaded (styles, images, fonts,
videos: the manifest of lib/dependencies.py) are those it was measured
with, with the same options of the measure and the same measuring script.
Its analysis is made again (the usual values of the deck may have moved).
Delete <config_dir>/.layout/ to measure everything again.

<config_dir>/.layout/summary.md lists all pages sorted by number of problems,
with the usual values of the deck (title position, columns, body font size,
...: also in deck.json), and contact_NN.png shows thumbnails of all pages.
Coordinates are in CSS pixels, origin at the top-left corner of the page
(1920x1080 for slides). One build at a time writes the report
(lib/report_lock.py).

The checks themselves are lib/layout/analysis.py, the markdown is
lib/layout/report.py, and the browser is lib/layout/measure.py. What this
module decides is everything that depends on the build: which pages to
measure, what to keep of a previous measure, where to write.

Options (configure.yaml, under `layout:`):
    layout:
      root: 'body'         # CSS selector of the content root
      exclude: 'nav, footer'   # children of the root that are not content
      width: 1920          # viewport size
      height: 1080
                           # these four describe the theme and are declared in
                           # its theme.yaml (lib/theme.py); a project sets them
                           # here only to override what its theme says
      images: render       # render.png and the contact sheets (the default);
                           # true: overlay.png, blocks.png, internal-overlay.png
                           # too; false: no image
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
from pathlib import Path
import shutil
import time
import traceback

from lib import dependencies
from lib.filesystem import shown
from lib.configuration import ConfigError
from lib.layout.analysis import analyse, deck_norms
from lib.layout.findings import count_problems
from lib.layout.measure import SCRIPTS, run_node_on, warn_degenerate_root, write_contact_sheets
from lib.layout.report import changes_markdown, layout_changes, page_markdown, summary_markdown
from lib.layout_options import jobs, options_of, output_directory, validate as validate_options
from lib.lint import Linter
from lib.report_lock import report_lock
from lib.structure import built_pages, page_path, structure

# The images of a page, by the value of the option `images` that writes them
IMAGES = {'render.png': (True, 'render'),
          'overlay.png': (True,), 'blocks.png': (True,), 'internal-overlay.png': (True,)}


def _clean_after_measure(output_dir, pages, previous, partial, start):
    """Once the measurement has run: the report of a page it could not write
    is removed (it would be read as fresh), and the reports of pages that
    are no longer in the site go with them. Nothing of this happens when the
    measurement fails: the report of the previous build is then kept whole."""
    for page in pages:                      # a page whose measure failed has no report
        path = os.path.join(page['out'], 'layout.json')
        try:
            if os.path.getmtime(path) < start:
                shutil.rmtree(page['out'], ignore_errors=True)
        except OSError:
            pass
    if not partial:                         # pages that left the site
        kept = {os.path.abspath(p['out']) for p in pages + previous}
        root = os.path.abspath(os.path.join(output_dir, 'pages'))
        for directory, _, files in os.walk(root, topdown=False):
            if 'layout.json' in files and os.path.abspath(directory) not in kept:
                shutil.rmtree(directory, ignore_errors=True)
        for directory, _, _ in os.walk(root, topdown=False):      # the directories left empty
            try:
                if os.path.abspath(directory) != root and not os.listdir(directory):
                    os.rmdir(directory)
            except OSError:
                pass


def _read_json(path):
    """The JSON of a file, or None when it cannot be read."""
    try:
        with open(path, encoding='utf-8') as fid:
            return json.load(fid)
    except (OSError, ValueError):
        return None


def _write(path, text):
    with open(path, 'w', encoding='utf-8', errors='replace', newline='\n') as fid:
        fid.write(text)


def _measure_key(options):
    """What a measure depends on besides the page: the options of the
    measure, the browser asked for and the script that measures."""
    return {**{k: options[k] for k in ('width', 'height', 'root', 'exclude', 'images', 'chrome')},
            'script': dependencies.file_hash(SCRIPTS / 'layout_measure.js')}


def _reusable(meta, page, key, hashes):
    """Whether the report of a page still describes what it shows: measured
    with the same options and script, from the same source, ready, every
    file it loaded unchanged (none outside the site's reach), its images
    there."""
    layout = _read_json(os.path.join(page['out'], 'layout.json'))
    if (layout is None or layout.get('measure') != key
            or layout.get('source') != shown(page['source'], meta.get('config_directory') or '.')
            or (layout.get('render_health') or {}).get('status') != 'ready'):
        return False
    manifest = layout.get('dependencies') or {}
    artifacts = manifest.get('artifacts') or {}
    if page['name'] not in artifacts or manifest.get('external_resources'):
        return False
    site = Path(meta['site_directory'])
    if any(dependencies.file_hash(site / relative, hashes) != expected
           for relative, expected in artifacts.items()):
        return False
    return all(os.path.isfile(os.path.join(page['out'], name))
               for name, written_by in IMAGES.items() if key['images'] in written_by)


def _same_source(report, page, meta):
    """Whether the report of a page (layout.json) was made from its source: the
    pages of a deck that changed may now have the path of another one."""
    layout = _read_json(report)
    return layout is not None and layout.get('source') == shown(page['source'], meta.get('config_directory') or '.')


def run(meta):
    """Measure the site and write the report. An analysis reports, or
    reports that it could not run: it never takes the build down with it. A
    missing browser used to throw away a site that had rendered
    correctly.

    What it is asked to do is another matter: a configuration it cannot make
    sense of (an unsafe output directory, an option of the wrong shape)
    stops the build, before anything is written, so that a typo is not
    answered by a report that never comes."""
    output = output_directory(meta)
    validate_options(meta, meta['log'])
    try:
        # one build at a time writes the reports (another build waits for it)
        with report_lock(output, meta['log']):
            return _measure_and_report(meta)
    except ConfigError:
        raise
    except Exception as error:
        meta['log'].error(f'Layout report not produced ({type(error).__name__}: {error}). '
                          f'The site is built; run --layout again once the cause is fixed.')
        meta['log'].debug(traceback.format_exc())


def _select_pages(meta, output_dir, requested):
    """The pages to measure, those whose report is kept (previous), the
    entries of the structure by page name, and whether the build is partial."""
    built = set(requested) if requested else {page_path(entry) for entry in built_pages(meta)}
    partial = len(built) < len(structure(meta))
    entries, pages, previous = {}, [], []
    for entry in structure(meta):
        relative = page_path(entry)
        if os.path.isabs(relative) or '..' in relative.replace('\\', '/').split('/'):
            raise ValueError(f'Invalid page path in layout structure: {relative}')
        entries[relative] = entry
        html = os.path.join(meta['site_directory'], relative)
        page = {'html': os.path.abspath(html),
                'out': os.path.abspath(os.path.join(output_dir, 'pages', relative)),
                'name': relative, 'source': entry['src'], 'layout': entry.get('layout')}
        if relative not in built:
            report = os.path.join(page['out'], 'layout.json')
            if partial and os.path.isfile(report) and (not requested or _same_source(report, page, meta)):
                previous.append(page)
            elif requested and os.path.isfile(html):       # its report is missing or of another page
                pages.append(page)
        elif os.path.isfile(html):
            pages.append(page)
    return pages, previous, entries, partial


def _analyse_page(meta, p, entry, layout, norms, options, linter):
    """The analysis of a page measured again, its lint, and what it depends on."""
    limits = {k: options[k] for k in ('max_words', 'min_font')}
    analyse(layout, options['threshold'], norms, limits, options.get('design_rules'))
    if p['source'] in (meta.get('lint_findings') or {}):       # lint of the build
        layout['analysis']['lint'] = meta['lint_findings'][p['source']]
    elif linter is not None and os.path.isfile(p['source']):
        layout['analysis']['lint'] = [f.as_dict() for f in linter.lint_file(p['source'], p['layout'])]
    layout['source'] = shown(p['source'], meta.get('config_directory') or '.')
    # the files the page depends on, to know whether a retained report is still valid
    meta.setdefault('runtime_resources', {})[p['name']] = layout.get('resources', [])
    layout['dependencies'] = dependencies.make_manifest(meta, entry, layout.get('resources', []))


def _measure_and_report(meta):
    options = options_of(meta)
    meta.setdefault('dependency_contexts', {})
    log = meta['log']
    output_dir = str(output_directory(meta))
    # --only: the pages built (or, when the pages of the site changed, the full
    # build measures only the pages named); the others keep their report
    requested = meta.get('measure')
    pages, previous, entries, partial = _select_pages(meta, output_dir, requested)
    key = _measure_key(options)
    hashes = {}                             # a file loaded by several pages is read once
    reused = [p for p in pages if _reusable(meta, p, key, hashes)]      # nothing it shows changed
    reused_names = {p['name'] for p in reused}
    pages = [p for p in pages if p['name'] not in reused_names]
    previous = previous + reused

    # Read (and do not remove) the previous measure of the pages measured
    # again, for changes.md: nothing is deleted before the measurement, so a
    # measurement that fails leaves the report of the previous build intact.
    previous_layouts = {}
    for p in pages:
        path = os.path.join(p['out'], 'layout.json')
        if not (requested and not _same_source(path, p, meta)):
            layout = _read_json(path)
            if layout is not None:
                previous_layouts[p['name']] = layout
    os.makedirs(output_dir, exist_ok=True)

    if requested:
        log.detail(f'--only: {len(pages)} page(s) measured; the pages of the site changed, '
                   f'the others keep their report (--layout for all)')
    log.detail(f'Measure layout of {len(pages)} pages ({len(reused)} unchanged, kept) ...')
    start = time.time()
    if pages:
        run_node_on('layout_measure.js', [{'html': p['html'], 'out': p['out'], 'name': p['name']} for p in pages],
                    [f"--root={options['root']}", f"--exclude={options['exclude']}",
                     f"--width={options['width']}", f"--height={options['height']}",
                     f"--images={ {True: 1, 'render': 'render', False: 0}[options['images']] }",
                     f"--jobs={jobs(options)}"],
                    'Measure layout', options['chrome'], log)
    _clean_after_measure(output_dir, pages, previous, partial, start)
    for p in pages:                         # images of another value of `images`: not of this measure
        for name, written_by in IMAGES.items():
            if options['images'] not in written_by:
                try:
                    os.remove(os.path.join(p['out'], name))
                except OSError:
                    pass

    remeasured = {p['name'] for p in pages}
    measured = []
    for p in previous + pages:
        layout_path = os.path.join(p['out'], 'layout.json')
        if os.path.isfile(layout_path):
            measured.append((p, layout_path, _read_json(layout_path)))
    warn_degenerate_root(measured, options, log)
    norms = deck_norms([layout for _, _, layout in measured])
    order = {page_path(entry): k for k, entry in enumerate(structure(meta))}
    measured.sort(key=lambda m: order[m[0]['name']])

    loaded_design = meta.get('loaded_design')
    linter = Linter(loaded_design) if loaded_design else None
    rows = []
    for p, layout_path, layout in measured:
        entry = entries[p['name']]
        if p['name'] in remeasured or p['name'] in reused_names:
            _analyse_page(meta, p, entry, layout, norms, options, linter)
        if p['name'] in remeasured:
            layout['measure'] = key
        # a retained measure: its validity is refreshed, not its geometry
        layout['freshness'] = dependencies.freshness(layout.get('dependencies'), meta, entry)
        _write(layout_path, json.dumps(layout, indent=1))
        _write(os.path.join(p['out'], 'layout.md'), page_markdown(p['name'], layout['source'], layout))
        rows.append((p['name'], shown(os.path.join(p['out'], 'layout.md'), output_dir), layout['analysis']))

    reference = os.path.join(meta['config_directory'], '.structure', 'design.md')
    _write(os.path.join(output_dir, 'summary.md'),
           summary_markdown(rows, norms, design=shown(reference, output_dir)
                            if loaded_design and any(loaded_design.values()) else None))
    changes = [(p['name'], lines) for p, _, layout in measured if p['name'] in remeasured
               and p['name'] in previous_layouts
               and (lines := layout_changes(previous_layouts[p['name']], layout))]
    _write(os.path.join(output_dir, 'changes.md'), changes_markdown(changes, len(pages)))
    _write(os.path.join(output_dir, 'deck.json'), json.dumps(norms, indent=1))
    if options['images'] and measured:
        write_contact_sheets(output_dir, [(p['name'], shown(p['out'], output_dir), layout['analysis'])
                                          for p, _, layout in measured],
                             measured[0][2]['viewport'], options, log,
                             changed={k for k, (p, _, _) in enumerate(measured) if p['name'] in remeasured}
                             if partial and not requested else None)      # deck changed: all the sheets

    n_problems = sum(count_problems(r[2]) for r in rows)
    if previous_layouts:
        log.info(f"Layout changes: {len(changes)} page(s) changed -> "
                 f"{shown(os.path.join(output_dir, 'changes.md'))}")
    log.info(f"Layout report: {len(pages)} measured{f', {len(reused)} unchanged' if reused else ''}, "
             f"{len(rows)} pages, {n_problems} problems -> "
             f"{shown(os.path.join(output_dir, 'summary.md'))}")
    if len(rows) < len(pages) + len(previous):
        raise RuntimeError(f'layout measurement failed for {len(pages) + len(previous) - len(rows)} page(s)')
