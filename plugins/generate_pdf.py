import os
import re
import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory

from lib.structure import load_structure, template_path

# Requires: puppeteer (npm i puppeteer), minimist (npm i minimist)

path_current_file = os.path.dirname(os.path.abspath(__file__)) + '/'


def remove_controls(meta, structure):
    for entry in structure:
        filepath = template_path(meta, entry)

        with open(filepath, 'r') as fid:
            file_content = fid.read()

        new_content = re.sub(r'(<video .*?)controls(.*?)>', r'\1\2>', file_content)
        new_content = new_content.replace('{controls}', '')

        with open(filepath, 'w') as fid:
            fid.write(new_content)


def pre_process(meta):
    structure = load_structure(meta['site_directory'])
    meta['log'].keyvalue('*', 'Remove video controls', indent_level=2)
    remove_controls(meta, structure)


def post_process(meta):
    structure = load_structure(meta['site_directory'])
    if not structure:
        raise ValueError('No pages to export as PDF')

    site_dir = os.path.abspath(meta['site_directory'])
    output_dir = os.path.dirname(site_dir)
    script = path_current_file + 'assets/template_html_to_pdf.js'

    # Stage fresh outputs so a failed export cannot reuse stale PDFs or remove
    # the HTML needed to diagnose/retry the failure.
    with TemporaryDirectory(prefix='pdf-export-', dir=output_dir) as staging:
        def export_page(item):
            counter, entry = item
            html_path = os.path.join(site_dir, entry['dir'], entry['filename'])
            stem = os.path.join(staging, 'slide_' + str(counter).zfill(3))
            pdf_path = stem + '.pdf'
            subprocess.run(['node', script, '--input=' + html_path,
                            '--output=' + pdf_path], check=True)
            if not os.path.isfile(pdf_path):
                raise RuntimeError(f'PDF not generated: {pdf_path}')
            subprocess.run(['pdftoppm', '-f', '1', '-singlefile', pdf_path, stem], check=True)
            subprocess.run(['magick', stem + '.ppm', '-resize', '3840', stem + '.jpg'], check=True)
            if not os.path.isfile(stem + '.jpg'):
                raise RuntimeError(f'Image not generated: {stem}.jpg')
            return pdf_path, stem + '.jpg'

        meta['log'].keyvalue('*', 'Generate PDF and images ...', indent_level=2)
        with ThreadPoolExecutor() as pool:
            outputs = list(pool.map(export_page, enumerate(structure)))

        merged = os.path.join(staging, 'slides.pdf')
        subprocess.run(['pdfunite', *[pdf for pdf, _ in outputs], merged], check=True)
        if not os.path.isfile(merged):
            raise RuntimeError('Merged PDF not generated')

        image_dir = os.path.join(output_dir, 'images')
        os.makedirs(image_dir, exist_ok=True)
        for _, image in outputs:
            shutil.copy2(image, image_dir)
        pdf_output = os.path.join(output_dir, 'slides.pdf')
        os.replace(merged, pdf_output)
        meta['log'].keyvalue('info', f"PDF file generated at '{pdf_output}'", indent_level=2)
        meta['log'].keyvalue('info', f"Images generated in '{image_dir}'", indent_level=2)

    # Only clean after every export and publication step succeeded.
    if not meta['debug']:
        shutil.rmtree(site_dir)
