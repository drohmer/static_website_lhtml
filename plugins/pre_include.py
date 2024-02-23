import sys
import os
import re
import json
import yaml

sys.path.append(os.path.dirname(os.path.abspath(__file__))+'/../lib')
import filesystem


def load_structure(site_directory):
    structure_path = site_directory+'/structure/structure.yaml'
    with open(structure_path) as fid:
        structure = yaml.load(fid, Loader=yaml.loader.SafeLoader)
    return structure



def pre_process(meta):

    # load structure
    structure = load_structure(meta['site_directory'])

    files_to_include = meta['plugin_arg']['pre_include']
    content_to_include = []
    for f in files_to_include:
        with open(f,'r') as fid:
            content_to_include.append(fid.read())

    for entry in structure:
        dirname = meta['site_directory'] + entry['dir']
        file_path = meta['site_directory'] + entry['dir'] + entry['filename'].replace('.html','.html.j2')
        
        with open(file_path,'r') as fid:
            file_content = fid.read()
        
        new_file_content = ''
        for entry in content_to_include:
            new_file_content += entry
            new_file_content += '\n'
        new_file_content += file_content
    
        with open(file_path,'w') as fid:
            fid.write(new_file_content)
        