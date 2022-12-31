import sys
import os
import re
import json
import yaml
from multiprocessing import Process

# Require installation of:
#  puppeteer (npm i puppeteer)
#  minimist (npm i minimist)

sys.path.append('lib')
sys.path.append('../lib')
import filesystem

path_current_file = os.path.dirname(os.path.abspath(__file__))+'/'


def load_structure(site_directory):
    structure_path = site_directory+'/structure/structure.yaml'
    with open(structure_path) as fid:
        structure = yaml.load(fid, Loader=yaml.loader.SafeLoader)
    return structure


def remove_controls(meta, structure):
     for entry in structure:
        filepath = meta['site_directory'] + entry['dir'] + entry['filename'].replace('.html','.html.j2')
        
        with open(filepath, 'r') as fid:
            file_content = fid.read()

        new_content = re.sub(r'(<video .*?)controls(.*?)>', r'\1\2', file_content)
        new_content = new_content.replace('{controls}','')

        with open(filepath,'w') as f:
            f.write(new_content)


def pre_process(meta):

    structure = load_structure(meta['site_directory'])

    # Need to remove video controls from the html.j2 source
    meta['log'].keyvalue('*','Remove video controls',indent_level=2)
    remove_controls(meta, structure)


def post_process(meta):

    structure = load_structure(meta['site_directory'])


    meta['log'].keyvalue('*','Generate pdf ...',indent_level=2)
    template_html_to_pdf_path = path_current_file+'assets/template_html_to_pdf.js'
    all_pdf = []
    procs = []
    for entry in structure:
        # print('\t\t - '+entry['dir'])
        path_in = os.path.abspath(meta['site_directory']+entry['dir']+entry['filename'])
        path_out = os.path.abspath(meta['site_directory']+entry['dir']+'output.pdf')
    
        cmd = f'node {template_html_to_pdf_path} --input={path_in} --output={path_out}'
        proc = Process(target=os.system, args=(cmd,))
        procs.append(proc)
        #os.system(cmd)

        all_pdf.append(path_out)
    
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()

    
    meta['log'].keyvalue('*','Merge pdf ...',indent_level=2)
    pdf_path_output = os.path.relpath(os.path.abspath(meta['site_directory']+'../slides.pdf'))
    all_pdf_txt = ' '.join(all_pdf)
    cmd = f'pdfunite {all_pdf_txt} {pdf_path_output}'
    os.system(cmd)
    if os.path.isfile(pdf_path_output):
        meta['log'].keyvalue('info',f'PDF file generated at \'{pdf_path_output}\'',indent_level=2)
    else:
        meta['log'].error(f'Cannot find PDF file')


    meta['log'].keyvalue('*','Generate images ...',indent_level=2)
    image_dir_path = str(os.path.relpath(os.path.abspath(meta['site_directory']+'../images/')))
    if not image_dir_path.endswith('/'):
        image_dir_path = image_dir_path + '/'
    os.system(f'mkdir -p {image_dir_path}')
    counter = 0

    procs = []
    for pdf_path in all_pdf:
        img_tmp_path = pdf_path.replace('output.pdf', 'out_img')

        # pdf -> ppm
        cmd_1 = f'pdftoppm {pdf_path} {img_tmp_path}'
        #os.system(cmd)

        # ppm -> jpg
        cmd_2 = f'convert {img_tmp_path}-1.ppm -resize 3840 {img_tmp_path}.jpg'
        #os.system(cmd)

        # move resulting image
        image_path = image_dir_path+'slide_'+str(counter).zfill(3)
        cmd_3 = f'cp {img_tmp_path}.jpg {image_path}.jpg'
        #os.system(cmd)
        counter = counter+1

        cmd = f'{cmd_1}; {cmd_2}; {cmd_3}'
        proc = Process(target=os.system, args=(cmd,))
        procs.append(proc)

    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()

    meta['log'].keyvalue('info',f'Images generated in \'{image_dir_path}\'',indent_level=2)

    # Clean after pdf directory
    if meta['debug']==False:
        meta['log'].keyvalue('*',f'Clean pdf directory',indent_level=2,debug_level=2)
        os.system('rm -rf '+meta['site_directory'])

