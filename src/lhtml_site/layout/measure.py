"""Measure the pages in headless Chromium, and write the images of the report.

Playwright for Python drives the browser (lhtml_site/browser.py); what runs
inside the page (the blocks, the overlays, the media frozen) is the
JavaScript of page.js, next to this file. The same browser renders the
contact sheets and the files of --render.
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path

from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Column

from lhtml_site import browser
from lhtml_site.layout.report import contact_sheets_html

PAGE_SCRIPT = Path(__file__).resolve().parent / 'page.js'
PALETTE = ['#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4', '#42d4f4',
           '#f032e6', '#bfef45', '#469990', '#9a6324', '#800000', '#808000',
           '#000075', '#fabed4', '#ffd8b1', '#aaffc3']
# --allow-file-access-from-files: the page reads its SVG images and GIFs
# (XMLHttpRequest on file://). The pages measured at the same time are not
# throttled as background pages (timers, rendering).
ARGS = ['--allow-file-access-from-files', '--disable-background-timer-throttling',
        '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows']
LOAD_TIMEOUT = 60_000           # ms
READY_TIMEOUT = 15              # s, for the fonts, images and readiness contract of a page
SETTLE = 0.15                   # s, for the deferred scripts of a page that does not say when it is ready
NETWORK_IDLE, NETWORK_TIMEOUT = 0.5, 5      # s


def _in_page(name):
    """The expression page.evaluate runs to call the function `name` of
    page.js with a list of arguments. The result comes back as JSON (what
    is undefined is left out, as JSON.stringify does)."""
    return ('async (args) => {\n' + PAGE_SCRIPT.read_text(encoding='utf-8')
            + f'\nconst result = await {name}(...args);\n'
            + 'return result === undefined ? null : JSON.stringify(result);\n}')


async def call(frame, name, *args):
    """Run the function `name` of page.js in a page (or a frame)."""
    result = await frame.evaluate(_in_page(name), list(args))
    return None if result is None else json.loads(result)


class _Bar:
    """The progress bar of a run in the browser (`label`), or none."""

    def __init__(self, label):
        self.progress = Progress(TextColumn('        {task.description}'), BarColumn(bar_width=24),
                                 MofNCompleteColumn(), TimeRemainingColumn(),
                                 TextColumn('{task.fields[item]}',
                                            table_column=Column(max_width=40, no_wrap=True, overflow='ellipsis')),
                                 transient=True, disable=label is None)
        self.task = self.progress.add_task(label or '', total=None, item='')

    def __enter__(self):
        self.progress.__enter__()
        return self

    def __exit__(self, *exc):
        return self.progress.__exit__(*exc)

    def update(self, done, total, item):
        self.progress.update(self.task, completed=done, total=total, item=item.removesuffix('/index.html'))


class _Network:
    """The requests of a page waiting for their response, to wait for the
    network to settle. A request is settled once its response arrived, not
    its whole body: a video streams for as long as it plays."""

    def __init__(self, page):
        self.pending, self.last = set(), 0.0
        loop = asyncio.get_running_loop()

        def started(request):
            self.pending.add(request)
            self.last = loop.time()

        def answered(request):
            self.pending.discard(request)
            self.last = loop.time()
        page.on('request', started)
        page.on('response', lambda response: answered(response.request))
        page.on('requestfailed', answered)
        page.on('requestfinished', lambda request: self.pending.discard(request))

    async def idle(self, quiet=NETWORK_IDLE, timeout=NETWORK_TIMEOUT):
        """Wait until no request was in flight for `quiet` seconds, at most
        `timeout` (a page streaming a video never gets there)."""
        loop = asyncio.get_running_loop()
        start = self.last = max(self.last, loop.time())
        while loop.time() - start < timeout:
            if not self.pending and loop.time() - self.last >= quiet:
                return
            await asyncio.sleep(0.05)


async def _local_frames(page):
    """The main frame and the visible local frames (file:, about:) of a page,
    at most 16 child frames: the frames whose content is waited for and
    measured."""
    frames = []
    for frame in page.frames:
        if len(frames) >= 17:
            break
        if frame == page.main_frame:
            frames.append(frame)
            continue
        if not frame.url.startswith(('file:', 'about:')):
            continue
        element = await frame.frame_element()
        box = await element.bounding_box()
        await element.dispose()
        if box and box['width'] > 0 and box['height'] > 0:
            frames.append(frame)
    return frames


async def _wait_for_content(frame):
    # A page that does not say when it is ready (a legacy page): its deferred
    # scripts (KaTeX auto-render, theme scripts) are given time to finish
    if not await call(frame, 'waitForContent'):
        await asyncio.sleep(SETTLE)


# ---------------------------------------------------------------------------
# The measure of the pages
# ---------------------------------------------------------------------------

def measure_pages(pages, options, jobs, log, label='Measure layout'):
    """Measure `pages` ([{'html', 'out', 'name'}]): for each one, write
    <out>/layout.json and the images of `options['images']` (True: render,
    overlays, blocks; 'render'; False: none). A page that fails is logged and
    has no layout.json; a browser that does not run raises a RuntimeError."""
    browser.require('The layout report')
    asyncio.run(_measure_pages(pages, options, jobs, log, label))


async def _measure_pages(pages, options, jobs, log, label):
    width, height = options['width'], options['height']
    queue = list(pages)
    counter = {'done': 0}

    async with browser.chromium(options.get('chrome'), ARGS) as chromium:
        with _Bar(label) as bar:
            # Each worker measures in a window of its own (a context of its
            # own). Chrome defers the loading of the videos of a hidden page
            # until it is shown: with tabs of one window, the videos of a
            # page waited the whole budget of freezeMedia (30 s) and were
            # measured without their dimensions.
            async def worker():
                context = await chromium.new_context(viewport={'width': width, 'height': height})
                page = await context.new_page()
                state = {'events': [], 'resources': []}
                network = _Network(page)
                page.on('request', lambda request: state['resources'].append(request.url))
                page.on('pageerror', lambda error: state['events'].append(
                    {'type': 'javascript', 'message': error.message}))

                # a media request the player cancels itself (to ask for
                # another range) is not a failure: a video that does not
                # load has video.error, or no dimensions (health)
                def failed(request):
                    if request.resource_type == 'media' and request.failure == 'net::ERR_ABORTED':
                        return
                    state['events'].append({'type': 'request', 'url': request.url,
                                            'message': request.failure or 'Request failed'})
                page.on('requestfailed', failed)
                page.on('response', lambda response: response.status >= 400 and state['events'].append(
                    {'type': 'http', 'url': response.url, 'status': response.status}))
                try:
                    while queue:
                        entry = queue.pop(0)
                        bar.update(counter['done'], len(pages), entry.get('name') or entry['html'])
                        state['events'], state['resources'] = [], []
                        try:
                            await _measure_page(page, network, entry, state, options)
                        except Exception as error:
                            log.error(f"layout_measure: {entry['html']}: {browser.first_line(error)}")
                        counter['done'] += 1
                finally:
                    await context.close()

            await asyncio.gather(*(worker() for _ in range(min(jobs, len(pages)) or 1)))
            bar.update(len(pages), len(pages), 'done')


async def _measure_page(page, network, entry, state, options):
    os.makedirs(entry['out'], exist_ok=True)
    # pages with streaming media (autoplay videos, iframes) never become
    # idle: wait for the load event, then for a short network idle
    await page.goto(Path(entry['html']).resolve().as_uri(), wait_until='load', timeout=LOAD_TIMEOUT)
    frames = await _local_frames(page)
    trusted = [await call(frame, 'trustedFrame') for frame in frames]
    if not trusted or not all(trusted):
        await network.idle()
    try:
        await asyncio.wait_for(asyncio.gather(*(_wait_for_content(frame) for frame in await _local_frames(page))),
                               READY_TIMEOUT)
    except asyncio.TimeoutError:
        raise RuntimeError('Content readiness timeout') from None
    await call(page, 'freezeMedia')
    await call(page, 'loadSvgImages')
    layout = await _snapshot(page, entry['out'], state, options)
    layout['resources'] = [url for url in dict.fromkeys(state['resources']) if not url.startswith('data:')]
    with open(os.path.join(entry['out'], 'layout.json'), 'w', encoding='utf-8', newline='\n') as fid:
        json.dump(layout, fid, indent=1, ensure_ascii=False)


async def _measure_frame(page, frame, state, checked_frames):
    # the health first: a video whose dimensions arrive while the blocks are
    # extracted was measured without them, and must say so
    health = await call(frame, 'renderHealth', checked_frames)
    main = frame == page.main_frame
    layout = await call(frame, 'extractBlocks', state['root'] if main else 'body', state['exclude'] if main else '')
    errors = state['events'] + [error for kind in ('images', 'fonts', 'math', 'video', 'sizeless', 'clock')
                                for error in health[kind]]
    layout['media_samples'] = await call(frame, 'mediaSamples')
    layout['render_health'] = {'status': 'incomplete' if errors else 'ready', 'errors': errors,
                               'unchecked': health['unchecked']}
    return layout


async def _snapshot(page, out, state, options):
    images = options['images']
    clip = {'x': 0, 'y': 0, 'width': options['width'], 'height': options['height']}
    await call(page, 'removeOverlay')
    layout = await _measure_frame(page, page.main_frame, {**state, 'root': options['root'],
                                                          'exclude': options['exclude']}, [])
    if images:
        await page.screenshot(path=os.path.join(out, 'render.png'), clip=clip)
    if images is True:
        for name, blocks, filled in (('internal-overlay.png', layout['subblocks'], False),
                                     ('overlay.png', layout['blocks'], False),
                                     ('blocks.png', layout['blocks'], True)):
            await call(page, 'drawOverlay', blocks, PALETTE, filled)
            await page.screenshot(path=os.path.join(out, name), clip=clip)
        await call(page, 'removeOverlay')
    return layout


# ---------------------------------------------------------------------------
# The contact sheets
# ---------------------------------------------------------------------------

def write_contact_sheets(output_dir, rows, viewport, options, log, changed=None):
    """Write contact_NN.html and screenshot them as contact_NN.png (only the
    sheets showing the pages `changed`, a set of row indices, when given). A
    sheet whose HTML is the one of its picture already is not taken again."""
    sheets = []
    per_sheet = options['contact_columns'] * options['contact_rows']
    for i, html in enumerate(contact_sheets_html(rows, viewport, options['contact_columns'],
                                                 options['contact_rows']), 1):
        if changed is not None and not any((i - 1) * per_sheet <= k < i * per_sheet for k in changed):
            continue
        html_path = os.path.abspath(os.path.join(output_dir, f'contact_{i:02d}.html'))
        png_path = html_path[:-len('.html')] + '.png'
        try:                                # the same sheet of the same pictures: kept
            shown_renders = [os.path.join(output_dir, rel, 'render.png')
                             for _, rel, _ in rows[(i - 1) * per_sheet:i * per_sheet]]
            with open(html_path, encoding='utf-8') as fid:
                if fid.read() == html and os.path.getmtime(png_path) >= max(
                        [os.path.getmtime(html_path)] + [os.path.getmtime(r) for r in shown_renders]):
                    continue
        except OSError:
            pass
        with open(html_path, 'w', encoding='utf-8', errors='replace', newline='\n') as fid:
            fid.write(html)
        sheets.append({'html': html_path, 'png': png_path})
    if not sheets:
        return
    screenshot_sheets(sheets, options['chrome'], log)


def screenshot_sheets(sheets, chrome, log, width=1920):
    """Screenshot the contact sheets ([{'html', 'png'}]), each one whole."""
    browser.require('The layout report')
    asyncio.run(_screenshot_sheets(sheets, chrome, log, width))


async def _screenshot_sheets(sheets, chrome, log, width):
    async with browser.chromium(chrome, ARGS) as chromium:
        page = await chromium.new_page(viewport={'width': width, 'height': 600})
        with _Bar('Contact sheets') as bar:
            for index, sheet in enumerate(sheets):
                bar.update(index, len(sheets), os.path.basename(sheet['png']))
                try:
                    await page.goto(Path(sheet['html']).resolve().as_uri(), wait_until='networkidle',
                                    timeout=LOAD_TIMEOUT)
                    await page.evaluate("""async () => {
                        await Promise.all([...document.images].filter(img => !img.complete).map(img =>
                            new Promise(resolve => { img.onload = img.onerror = resolve; })));
                    }""")
                    await page.screenshot(path=sheet['png'], full_page=True)
                except Exception as error:
                    log.error(f"layout_contact: {sheet['html']}: {browser.first_line(error)}")


# ---------------------------------------------------------------------------
# --render: files as the slides draw them
# ---------------------------------------------------------------------------

def render_files(entries, width, height, chrome):
    """Render files as PNG as the slides draw them (fonts, SVG text), without
    building the site: an image (SVG, PNG...) at its size, at most the
    slide, on a white page; a page (HTML) at the size of the slide.
    `entries`: [{'file', 'png'}]. Returns the errors, one line per file that
    could not be rendered."""
    browser.require('--render')
    return asyncio.run(_render_files(entries, width, height, chrome))


async def _render_files(entries, width, height, chrome):
    errors = []
    async with browser.chromium(chrome, ARGS) as chromium:
        page = await chromium.new_page(viewport={'width': width, 'height': height})
        network = _Network(page)
        for entry in entries:
            try:
                os.makedirs(os.path.dirname(entry['png']), exist_ok=True)
                url = Path(entry['file']).resolve().as_uri()
                if entry['file'].lower().endswith(('.html', '.htm')):
                    await page.goto(url, wait_until='load', timeout=LOAD_TIMEOUT)
                    await network.idle()
                    await page.screenshot(path=entry['png'])
                    continue
                # an image on a white page, at its size (at most the slide)
                # (a page of file://, which may show the files: not about:blank)
                with tempfile.TemporaryDirectory(prefix='render-') as holder:
                    holder = Path(holder) / 'index.html'
                    holder.write_text(f'<html><body style="margin:0;background:white">'
                                      f'<img id="f" style="display:block;max-width:{width}px;'
                                      f'max-height:{height}px" src="{url}"></body></html>', encoding='utf-8')
                    await page.goto(holder.as_uri(), wait_until='load')
                ok = await page.evaluate("""() => new Promise(resolve => {
                    const img = document.getElementById('f');
                    const done = () => resolve(img.naturalWidth > 0);
                    if (img.complete) done(); else { img.onload = done; img.onerror = done; }
                })""")
                if not ok:
                    raise RuntimeError('cannot read the image')
                await page.evaluate('async () => { await document.fonts.ready; }')
                await page.locator('#f').screenshot(path=entry['png'])
            except Exception as error:
                errors.append(f"render_file: {entry['file']}: {browser.first_line(error)}")
    return errors


def warn_degenerate_root(measured, options, log):
    """A root selector that does not match the theme gives one block per page:
    the whole content is a single box, and every check on the blocks
    (collisions, alignment, gaps) is then empty while the report looks
    healthy. Say so, with the root actually used."""
    degenerate = [p['name'] for p, _, layout in measured if len(layout.get('blocks') or []) <= 1]
    if len(degenerate) < len(measured) or not measured:
        return                      # a single page may legitimately hold one block
    used = measured[0][2].get('root') or options['root']
    log.warning(f"Layout report: every page was measured as a single block (root: '{used}'). "
                f"The root selector probably does not match the theme; the checks on the blocks "
                f"found nothing. The theme declares its content element in its theme.yaml "
                f"('layout: root:', lhtml_site/theme.py); a project overrides it under 'layout:'.")
