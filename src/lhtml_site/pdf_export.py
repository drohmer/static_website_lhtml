"""The PDF export of a target whose theme declares `export: pdf`.

The build renders the pages with that theme, as a site, then exports them:
each page to a PDF by Chrome (plugins/assets/template_html_to_pdf.js), the
PDFs merged into `<name>.pdf`, and the first page of each to
`images/slide_NNN.jpg`, next to the site directory - in the directory of the
deck. The site was an intermediate: it is not published, unless --debug
keeps it or --only built in the site itself.

Requires node (puppeteer), pdftoppm and pdfunite (poppler), magick.
"""
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from lhtml_site.layout.measure import PUPPETEER_MISSING
from lhtml_site.structure import built_pages, page_path, structure, template_path

SCRIPT = Path(__file__).resolve().parent / 'plugins/assets/template_html_to_pdf.js'
# Chrome loads a page within 4 s (the script); a page showing videos misses it
# when too many Chromes run at once: a few at a time, and a page that missed
# it is tried again before the export fails
JOBS = min(6, os.cpu_count() or 1)
ATTEMPTS = 3


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


def export(meta):
    """Export the pages of the site to <name>.pdf and images/ next to it."""
    pages = structure(meta)
    if not pages:
        raise ValueError('No pages to export as PDF')
    site = Path(meta['site_directory']).resolve()
    output = site.parent
    name = meta.get('export_name') or 'slides'
    chrome = ['--chrome=' + meta['chrome']] if meta.get('chrome') else []

    # Fresh outputs in a staging directory: a failed export reuses no stale
    # PDF, and removes no HTML that would help to diagnose it.
    with TemporaryDirectory(prefix='pdf-export-', dir=output) as staging:
        def export_page(item):
            counter, entry = item
            stem = os.path.join(staging, 'slide_' + str(counter).zfill(3))
            pdf = stem + '.pdf'
            command = ['node', str(SCRIPT), '--input=' + str(site / page_path(entry)), '--output=' + pdf] + chrome
            for attempt in range(ATTEMPTS):
                result = subprocess.run(command, capture_output=True, text=True)
                if result.returncode == 0:
                    break
            else:
                if 'Cannot find module' in result.stderr:
                    raise RuntimeError(PUPPETEER_MISSING)
                lines = result.stderr.strip().splitlines()
                said = next((line for line in lines if 'Error' in line), lines[0] if lines else result.returncode)
                raise RuntimeError(f"PDF of {page_path(entry)} not made after {ATTEMPTS} attempts: {said}")
            if not os.path.isfile(pdf):
                raise RuntimeError(f'PDF not generated: {pdf}')
            subprocess.run(['pdftoppm', '-f', '1', '-singlefile', pdf, stem], check=True)
            subprocess.run(['magick', stem + '.ppm', '-resize', '3840', stem + '.jpg'], check=True)
            if not os.path.isfile(stem + '.jpg'):
                raise RuntimeError(f'Image not generated: {stem}.jpg')
            return pdf, stem + '.jpg'

        meta['log'].detail(f'PDF of {len(pages)} page(s) ...')
        with ThreadPoolExecutor(max_workers=JOBS) as pool:
            outputs = list(pool.map(export_page, enumerate(pages)))

        merged = os.path.join(staging, name + '.pdf')
        subprocess.run(['pdfunite', *[pdf for pdf, _ in outputs], merged], check=True)
        if not os.path.isfile(merged):
            raise RuntimeError('Merged PDF not generated')

        images = output / 'images'
        images.mkdir(exist_ok=True)
        for old in images.glob('slide_*.jpg'):     # a deck that lost slides keeps none of theirs
            old.unlink()
        for _, image in outputs:
            shutil.copy2(image, images)
        os.replace(merged, output / (name + '.pdf'))
        meta['exported'] = output / (name + '.pdf')         # what the build says it made
        meta['log'].detail(f'images in {images}')

    if not meta['debug'] and not meta.get('only'):
        meta['publish_site'] = False
