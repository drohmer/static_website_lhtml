import os
import re
import yaml # pip install pyyaml
import json



def extract_data_from_file(file, regex):
    # Read file
    file_content = ''
    with open(file,'r') as fid:
        file_content = fid.read()
    
    #compile regex
    for r in regex:
        regex_compiled = re.compile(r,  re.DOTALL | re.MULTILINE)
        match = re.findall(regex_compiled, file_content)
        if len(match)>=1:
            data = match[0]
            return data
    
    print('Failed to extract data in file ',file)

def clean_string(s):
    
    s = s.strip()
    if s.startswith("'"):
        s = s[1:]
    if s.startswith('"'):
        s = s[1:]
    if s.endswith("'"):
        s = s[:-1]
    if s.endswith('"'):
        s = s[:-1]
    return s


def extract_titles(template_files):

    for entry in template_files:
        path = entry['path'].filepath()
        regex = [r'tocTitle.*?=(.*?)%}', r'pageTitle.*?=(.*?)%}', r'^=+ (.*?)$']    
        title = extract_data_from_file(path, regex)
        
        entry['title'] = clean_string(title)


def export_structure(template_files, structure_path, root_path):

    structure_to_export = []
    for entry in template_files:
        dir_path = entry['path'].path_local
        file_path = entry['path'].filename.replace('.html.j2','.html')

        level_toc = 0
        if 'extra-config' in entry:
            if 'level-toc' in entry['extra-config']:
                level_toc = entry['extra-config']['level-toc']

        structure_to_export.append({'dir':dir_path,'filename':file_path,'level':entry['path'].level,'title':entry['title'], 'level_toc':level_toc})
        

    if not os.path.isdir(structure_path):
        os.system(f'mkdir {structure_path}')
    path_yaml = structure_path + 'structure.yaml'
    path_json = structure_path + 'structure.json'
    
    with open(path_yaml,'w') as fid:
        yaml.dump(structure_to_export, fid)
    with open(path_json,'w') as fid:
        json.dump(structure_to_export, fid, indent=4)

def print_debug(msg, debug, level_base=0, level=0):
    if debug==True:
        level_str = '\t'*(level_base+level)
        print(level_str+msg)
    

def extract_additional_config(template_files):
    for k,entry in enumerate(template_files):
        config_path = entry['path'].root_directory+entry['path'].path_local+'config.yaml'
        if os.path.isfile(config_path):
            with open(config_path, 'r') as fid:
                template_files[k]['extra-config'] = yaml.safe_load(fid)
