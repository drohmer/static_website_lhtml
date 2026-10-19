"""The PDF export of a target whose theme declares `export: pdf`.

The build renders the pages with that theme, as a site, then exports them:
each page to a PDF, the PDFs merged into `<name>.pdf`, and an image of each
page to `images/slide_NNN.jpg`, next to the site directory - in the directory
of the deck. The site was an intermediate: it is not published, unless
--debug keeps it or --only built in the site itself.

The pages are exported by Playwright (the extra `lhtml-site[pdf]`:
playwright, pypdf, and the Chromium of
`python -m playwright install --only-shell chromium`; lhtml_site/browser.py):
one browser for the deck, a few pages at a time, each printed once it is
ready (fonts, math, images, videos) rather than after a fixed delay; its
image is a screenshot at 3840 px wide, the PDFs merged by pypdf.
"""
import asyncio
import os
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from lhtml_site import browser
from lhtml_site.structure import built_pages, page_path, structure, template_path

# Pages printed at the same time
JOBS = min(6, os.cpu_count() or 1)

# The page of the PDF (the slide is 1920x1080: a few pixels more keep a slide
# on one page), and the width of its image
PAGE_WIDTH, PAGE_HEIGHT = 1925, 1085
IMAGE_WIDTH = 3840
JPEG_QUALITY = 92                   # the default of magick for an image without one
# The longest a page may take to load and become ready. A clock
# no longer decides when a page is printed: it only bounds a page that never
# gets ready, which is then an error.
READY_TIMEOUT = 60_000              # ms
VIDEO_TIMEOUT = 15_000              # ms, for the first frame of each video

PDF_MODULES = ('playwright', 'pypdf')

# Ready when: the page has loaded (its deferred scripts ran: KaTeX auto-render
# included), MathJax (if any) has typeset, the fonts are loaded (KaTeX loads
# its own once it has rendered), the images are decoded, each video shows a
# frame, and the page has painted twice.
READY = """async ({videoTimeout}) => {
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

# The image shows the page as printed: the PDF is printed without the
# backgrounds (the default of Chrome: the icons of the navigation are backgrounds), except where the page asks for them
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
    return browser.installed(PDF_MODULES)


def export(meta):
    """Export the pages of the site to <name>.pdf and images/ next to it."""
    pages = structure(meta)
    if not pages:
        raise ValueError('No pages to export as PDF')
    site = Path(meta['site_directory']).resolve()
    output = site.parent
    name = meta.get('export_name') or 'slides'

    # Fresh outputs in a staging directory: a failed export reuses no stale
    # PDF, and removes no HTML that would help to diagnose it.
    with TemporaryDirectory(prefix='pdf-export-', dir=output) as staging:
        stems = [os.path.join(staging, 'slide_' + str(counter).zfill(3)) for counter in range(len(pages))]
        inputs = [site / page_path(entry) for entry in pages]
        meta['log'].detail(f'PDF of {len(pages)} page(s) ...')
        export_playwright(inputs, stems, meta.get('chrome'))
        for stem in stems:
            for file in (stem + '.pdf', stem + '.jpg'):
                if not os.path.isfile(file) or not os.path.getsize(file):
                    raise RuntimeError(f'{"PDF" if file.endswith(".pdf") else "Image"} not generated: {file}')

        merged = os.path.join(staging, name + '.pdf')
        merge_pypdf([stem + '.pdf' for stem in stems], merged)
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
# Playwright: one browser, pages printed once ready, screenshots, pypdf
# ---------------------------------------------------------------------------

def export_playwright(inputs, stems, chrome_path=None):
    browser.require('The PDF export', PDF_MODULES)
    asyncio.run(_export_playwright(inputs, stems, chrome_path))


async def _export_playwright(inputs, stems, chrome_path):
    from playwright.async_api import Error

    async with browser.chromium(chrome_path) as chromium:
        # The viewport is the page of the PDF, drawn at the width of the image
        context = await chromium.new_context(viewport={'width': PAGE_WIDTH, 'height': PAGE_HEIGHT},
                                             device_scale_factor=IMAGE_WIDTH / PAGE_WIDTH)
        slots = asyncio.Semaphore(JOBS)

        async def export_page(source, stem):
            async with slots:
                page = await context.new_page()
                try:
                    await page.goto(source.as_uri(), wait_until='load', timeout=READY_TIMEOUT)
                    await page.evaluate(READY, {'videoTimeout': VIDEO_TIMEOUT})
                    await page.pdf(path=stem + '.pdf', width=f'{PAGE_WIDTH}px', height=f'{PAGE_HEIGHT}px',
                                   margin={'top': '0px', 'left': '0px', 'right': '0px', 'bottom': '0px'})
                    # The image of the page as printed: print media, as in the PDF
                    await page.emulate_media(media='print')
                    await page.evaluate(AS_PRINTED)
                    await page.screenshot(path=stem + '.jpg', type='jpeg', quality=JPEG_QUALITY)
                except Error as error:
                    raise RuntimeError(f'PDF of {source} not made: {browser.first_line(error)}') from None
                finally:
                    await page.close()

        await asyncio.gather(*(export_page(source, stem) for source, stem in zip(inputs, stems)))


def merge_pypdf(pdfs, merged):
    from pypdf import PdfWriter
    writer = PdfWriter()
    for pdf in pdfs:
        writer.append(pdf)
    with open(merged, 'wb') as fid:
        writer.write(fid)
