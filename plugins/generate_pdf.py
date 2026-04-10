import os
import re
import subprocess
import shutil
from multiprocessing import Process

from lib.structure import load_structure

# Requires: puppeteer (npm i puppeteer), minimist (npm i minimist)

path_current_file = os.path.dirname(os.path.abspath(__file__)) + '/'


def remove_controls(meta, structure):
    for entry in structure:
        filepath = meta['site_directory'] + entry['dir'] + entry['filename'].replace('.html', '.html.j2')

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

    meta['log'].keyvalue('*', 'Generate pdf ...', indent_level=2)
    template_html_to_pdf_path = path_current_file + 'assets/template_html_to_pdf.js'
    all_pdf = []
    procs = []
    for entry in structure:
        path_in = os.path.abspath(meta['site_directory'] + entry['dir'] + entry['filename'])
        path_out = os.path.abspath(meta['site_directory'] + entry['dir'] + 'output.pdf')

        cmd = f'node {template_html_to_pdf_path} --input={path_in} --output={path_out}'
        proc = Process(target=os.system, args=(cmd,))
        procs.append(proc)
        all_pdf.append(path_out)

    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()

    meta['log'].keyvalue('*', 'Merge pdf ...', indent_level=2)
    pdf_path_output = os.path.relpath(os.path.abspath(meta['site_directory'] + '../slides.pdf'))
    all_pdf_txt = ' '.join(all_pdf)
    subprocess.run(f'pdfunite {all_pdf_txt} {pdf_path_output}', shell=True)
    if os.path.isfile(pdf_path_output):
        meta['log'].keyvalue('info', f"PDF file generated at '{pdf_path_output}'", indent_level=2)
    else:
        meta['log'].error('Cannot find PDF file')

    meta['log'].keyvalue('*', 'Generate images ...', indent_level=2)
    image_dir_path = os.path.relpath(os.path.abspath(meta['site_directory'] + '../images/'))
    if not image_dir_path.endswith('/'):
        image_dir_path += '/'
    os.makedirs(image_dir_path, exist_ok=True)

    procs = []
    for counter, pdf_path in enumerate(all_pdf):
        img_tmp_path = pdf_path.replace('output.pdf', 'out_img')
        image_path = image_dir_path + 'slide_' + str(counter).zfill(3)

        cmd = f'pdftoppm {pdf_path} {img_tmp_path}; magick {img_tmp_path}-1.ppm -resize 3840 {img_tmp_path}.jpg; cp {img_tmp_path}.jpg {image_path}.jpg'
        proc = Process(target=os.system, args=(cmd,))
        procs.append(proc)

    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()

    meta['log'].keyvalue('info', f"Images generated in '{image_dir_path}'", indent_level=2)

    # Clean pdf directory
    if not meta['debug']:
        meta['log'].keyvalue('*', 'Clean pdf directory', indent_level=2, debug_level=2)
        site_dir = meta['site_directory']
        if os.path.isdir(site_dir):
            shutil.rmtree(site_dir)
