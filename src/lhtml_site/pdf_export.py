"""The PDF export of a target whose theme declares `export: pdf`.

The build renders the pages with that theme, as a site, then exports them:
each page to a PDF, the PDFs merged into `<name>.pdf`, and an image of each
page to `images/slide_NNN.jpg`, next to the site directory - in the directory
of the deck. The site was an intermediate: it is not published, unless
--debug keeps it or --only built in the site itself.

Two engines make the same files:

- playwright (the extra `lhtml-site[pdf]`: playwright, pypdf, and the
  Chromium of `python -m playwright install --only-shell chromium`): one browser for the
  deck, a few pages at a time, each printed once it is ready (fonts, math,
  images, videos) rather than after a fixed delay; its image is a screenshot
  at 3840 px wide, the PDFs merged by pypdf.
- node (the fallback): a Chrome per page by puppeteer
  (plugins/assets/template_html_to_pdf.js), its first page rendered by
  pdftoppm (poppler) and resized by magick, the PDFs merged by pdfunite.

The playwright engine is used when playwright and pypdf are importable;
LHTML_PDF_ENGINE=node (or playwright) chooses one.
"""
import asyncio
import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from lhtml_site.doctor import installation, node_environment, playwright_browser_command
from lhtml_site.layout.measure import PUPPETEER_MISSING
from lhtml_site.structure import built_pages, page_path, structure, template_path

SCRIPT = Path(__file__).resolve().parent / 'plugins/assets/template_html_to_pdf.js'
# Chrome loads a page within 4 s (the script); a page showing videos misses it
# when too many Chromes run at once: a few at a time, and a page that missed
# it is tried again before the export fails
JOBS = min(6, os.cpu_count() or 1)
ATTEMPTS = 3

# The page of the PDF (the slide is 1920x1080: a few pixels more keep a slide
# on one page), and the width of its image
PAGE_WIDTH, PAGE_HEIGHT = 1925, 1085
IMAGE_WIDTH = 3840
JPEG_QUALITY = 92                   # the default of magick for an image without one
# Playwright: the longest a page may take to load and become ready. A clock
# no longer decides when a page is printed: it only bounds a page that never
# gets ready, which is then an error.
READY_TIMEOUT = 60_000              # ms
VIDEO_TIMEOUT = 15_000              # ms, for the first frame of each video

ENGINES = ('playwright', 'node')
PLAYWRIGHT_MISSING = ('The PDF export needs playwright and pypdf: {install}, '
                      'then {browser} '
                      '(or LHTML_PDF_ENGINE=node for the Node export)')
CHROMIUM_MISSING = ('The Chromium of Playwright is not installed: {browser} '
                    '(or the configuration key chrome)')

# Ready when: the page has loaded (its deferred scripts ran: KaTeX auto-render
# included), the promises a page or a demo registered with window.__lhtmlReady
# (themes/slides/js/readiness.js) are settled, MathJax (if any) has typeset, the fonts are loaded (KaTeX loads
# its own once it has rendered), the images are decoded, each video shows a
# frame, and the page has painted twice.
READY = """async ({videoTimeout}) => {
    if (window.__lhtmlReady?.version === 1) {
        await window.__lhtmlReady.ready();
    }
    if (window.MathJax && MathJax.startup && MathJax.startup.promise) {
        await MathJax.startup.promise;
    }
    await document.fonts.ready;
    await Promise.all([...document.images].map(img =>
        img.complete && img.naturalWidth ? null : img.decode().catch(() => null)));
    await Promise.all([...document.querySelectorAll('video')].map(video =>
        video.readyState >= 2 || video.preload === 'none' || video.error ? null :
        new Promise(done => {
            video.addEventListener('loadeddata', done, {once: true});
            video.addEventListener('error', done, {once: true});
            setTimeout(done, videoTimeout);
        })));
    await document.fonts.ready;
    await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
}"""

# A frame of the page (a demo in an iframe) registers its promises in its own window
FRAME_READY = """async () => {
    if (window.__lhtmlReady?.version === 1) {
        await window.__lhtmlReady.ready();
    }
}"""

# The image shows the page as printed: the PDF is printed without the
# backgrounds (the default of Chrome, which the Node export kept: the icons
# of the navigation are backgrounds), except where the page asks for them
# (print-color-adjust: exact). A screenshot draws them: removed first.
AS_PRINTED = """() => {
    for (const element of document.querySelectorAll('*')) {
        if (getComputedStyle(element).printColorAdjust !== 'exact') {
            element.style.setProperty('background-image', 'none', 'important');
            element.style.setProperty('background-color', 'transparent', 'important');
        }
    }
    return new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
}"""


def remove_video_controls(meta):
    """A page of a PDF does not play: no controls on its videos (templates of
    the pages built, before Jinja)."""
    for entry in built_pages(meta):
        path = template_path(meta, entry)
        with open(path, encoding='utf-8') as fid:
            text = fid.read()
        text = re.sub(r'(<video .*?)controls(.*?)>', r'\1\2>', text).replace('{controls}', '')
        with open(path, 'w', encoding='utf-8', newline='\n') as fid:
            fid.write(text)


def playwright_available():
    return all(importlib.util.find_spec(module) for module in ('playwright', 'pypdf'))


def engine():
    """The engine of the export: LHTML_PDF_ENGINE, else playwright when it is
    installed, else node."""
    asked = os.environ.get('LHTML_PDF_ENGINE', '').strip().lower()
    if asked:
        if asked not in ENGINES:
            raise ValueError(f"LHTML_PDF_ENGINE: '{asked}' is not one of {', '.join(ENGINES)}")
        return asked
    return 'playwright' if playwright_available() else 'node'


def export(meta):
    """Export the pages of the site to <name>.pdf and images/ next to it."""
    pages = structure(meta)
    if not pages:
        raise ValueError('No pages to export as PDF')
    site = Path(meta['site_directory']).resolve()
    output = site.parent
    name = meta.get('export_name') or 'slides'
    chosen = engine()

    # Fresh outputs in a staging directory: a failed export reuses no stale
    # PDF, and removes no HTML that would help to diagnose it.
    with TemporaryDirectory(prefix='pdf-export-', dir=output) as staging:
        stems = [os.path.join(staging, 'slide_' + str(counter).zfill(3)) for counter in range(len(pages))]
        inputs = [site / page_path(entry) for entry in pages]
        meta['log'].detail(f'PDF of {len(pages)} page(s) ({chosen}) ...')
        with meta['log'].progress(f'PDF ({chosen})', len(pages)) as done:
            try:
                if chosen == 'playwright':
                    export_playwright(inputs, stems, meta.get('chrome'), done=done)
                else:
                    export_node(inputs, stems, meta.get('chrome'), done=done)
            except RuntimeError as error:
                # Neither engine installed: the one to install is Playwright,
                # not the Node export it fell back to
                if chosen == 'node' and not os.environ.get('LHTML_PDF_ENGINE', '').strip() \
                        and str(error) == PUPPETEER_MISSING:
                    raise RuntimeError(playwright_missing()) from None
                raise
        for stem in stems:
            for file in (stem + '.pdf', stem + '.jpg'):
                if not os.path.isfile(file) or not os.path.getsize(file):
                    raise RuntimeError(f'{"PDF" if file.endswith(".pdf") else "Image"} not generated: {file}')

        merged = os.path.join(staging, name + '.pdf')
        if chosen == 'playwright':
            merge_pypdf([stem + '.pdf' for stem in stems], merged)
        else:
            subprocess.run(['pdfunite', *[stem + '.pdf' for stem in stems], merged], check=True)
        if not os.path.isfile(merged):
            raise RuntimeError('Merged PDF not generated')

        images = output / 'images'
        images.mkdir(exist_ok=True)
        for old in images.glob('slide_*.jpg'):     # a deck that lost slides keeps none of theirs
            old.unlink()
        for stem in stems:
            shutil.copy2(stem + '.jpg', images)
        os.replace(merged, output / (name + '.pdf'))
        meta['exported'] = output / (name + '.pdf')         # what the build says it made
        meta['log'].detail(f'images in {images}')

    if not meta['debug'] and not meta.get('only'):
        meta['publish_site'] = False


# ---------------------------------------------------------------------------
# Node: a Chrome per page by puppeteer, poppler and ImageMagick
# ---------------------------------------------------------------------------

def export_node(inputs, stems, chrome_path=None, done=lambda: None):
    chrome = ['--chrome=' + chrome_path] if chrome_path else []

    def export_page(item):
        page, stem = item
        pdf = stem + '.pdf'
        command = ['node', str(SCRIPT), '--input=' + str(page), '--output=' + pdf] + chrome
        for attempt in range(ATTEMPTS):
            result = subprocess.run(command, capture_output=True, text=True, env=node_environment())
            if result.returncode == 0:
                break
        else:
            if 'Cannot find module' in result.stderr:
                raise RuntimeError(PUPPETEER_MISSING)
            lines = result.stderr.strip().splitlines()
            said = next((line for line in lines if 'Error' in line), lines[0] if lines else result.returncode)
            raise RuntimeError(f"PDF of {page} not made after {ATTEMPTS} attempts: {said}")
        if not os.path.isfile(pdf):
            raise RuntimeError(f'PDF not generated: {pdf}')
        subprocess.run(['pdftoppm', '-f', '1', '-singlefile', pdf, stem], check=True)
        subprocess.run(['magick', stem + '.ppm', '-resize', str(IMAGE_WIDTH), stem + '.jpg'], check=True)
        done()

    with ThreadPoolExecutor(max_workers=JOBS) as pool:
        list(pool.map(export_page, zip(inputs, stems)))


# ---------------------------------------------------------------------------
# Playwright: one browser, pages printed once ready, screenshots, pypdf
# ---------------------------------------------------------------------------

def playwright_missing():
    """What to install for the Playwright export, for the way lhtml-site is installed."""
    python = shlex.quote(sys.executable)        # pipx puts it under "Application Support" on macOS
    install = ('pipx inject --include-apps lhtml-site playwright pypdf' if installation() == 'pipx'
               else f'{python} -m pip install "lhtml-site[pdf]"')
    return PLAYWRIGHT_MISSING.format(install=install, browser=playwright_browser_command())


def export_playwright(inputs, stems, chrome_path=None, done=lambda: None):
    if not playwright_available():
        raise RuntimeError(playwright_missing())
    asyncio.run(_export_playwright(inputs, stems, chrome_path, done))


async def _export_playwright(inputs, stems, chrome_path, done=lambda: None):
    from playwright.async_api import Error, async_playwright

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(executable_path=chrome_path or None)
        except Error as error:
            if "Executable doesn't exist" in str(error):
                raise RuntimeError(CHROMIUM_MISSING.format(browser=playwright_browser_command())) from None
            raise
        try:
            # The viewport is the page of the PDF, drawn at the width of the image
            context = await browser.new_context(viewport={'width': PAGE_WIDTH, 'height': PAGE_HEIGHT},
                                                device_scale_factor=IMAGE_WIDTH / PAGE_WIDTH)
            slots = asyncio.Semaphore(JOBS)

            async def export_page(source, stem):
                async with slots:
                    page = await context.new_page()
                    try:
                        # One bound for the whole preparation of the page: a
                        # promise that never settles (MathJax, a demo) fails it
                        try:
                            async with asyncio.timeout(READY_TIMEOUT / 1000):
                                await page.goto(source.as_uri(), wait_until='load', timeout=READY_TIMEOUT)
                                for frame in page.frames[1:]:
                                    await frame.evaluate(FRAME_READY)
                                await page.evaluate(READY, {'videoTimeout': VIDEO_TIMEOUT})
                        except TimeoutError:
                            raise RuntimeError(f'PDF of {source} not made: the page was not ready '
                                               f'after {READY_TIMEOUT // 1000} s') from None
                        await page.pdf(path=stem + '.pdf', width=f'{PAGE_WIDTH}px', height=f'{PAGE_HEIGHT}px',
                                       margin={'top': '0px', 'left': '0px', 'right': '0px', 'bottom': '0px'})
                        # The image of the page as printed: print media, as in the PDF
                        await page.emulate_media(media='print')
                        await page.evaluate(AS_PRINTED)
                        await page.screenshot(path=stem + '.jpg', type='jpeg', quality=JPEG_QUALITY)
                        done()
                    except Error as error:
                        said = str(error).strip().splitlines()[0]
                        raise RuntimeError(f'PDF of {source} not made: {said}') from None
                    finally:
                        await page.close()

            await asyncio.gather(*(export_page(source, stem) for source, stem in zip(inputs, stems)))
        finally:
            await browser.close()


def merge_pypdf(pdfs, merged):
    from pypdf import PdfWriter
    writer = PdfWriter()
    for pdf in pdfs:
        writer.append(pdf)
    with open(merged, 'wb') as fid:
        writer.write(fid)
