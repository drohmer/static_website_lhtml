import os
import re
import yaml # pip install pyyaml
import json



def clean_string(s):
    if s==None:
        return "unknown"

    s = s.strip()
    s = s.replace("'",'')
    s = s.replace("'",'')
    s = s.strip()

    return s

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

def extract_title_id_from_file(path, title):

    file_content = ''
    with open(path,'r') as fid:
        file_content = fid.read()

    regex = r'title_id.*?=(.*?)%}'

    regex_compiled = re.compile(regex,  re.DOTALL | re.MULTILINE)
    match = re.findall(regex_compiled, file_content)
    if len(match)>=1:
        data = match[0]
    else:
        data = title
    return clean_string(data).replace(' ','_').replace('#','').lower()



  
def generate_unique_id(title_id, sitemap):

    if title_id in sitemap:
        k = 1
        attempt = title_id
        while attempt in sitemap:
            attempt = title_id+'_'+str(k)
            k = k+1
        title_id = attempt

    return title_id

def extract_titles(template_files):

    sitemap = {}

    for entry in template_files:
        path = entry['path'].filepath()
        regex = [r'tocTitle.*?=(.*?)%}', r'pageTitle.*?=(.*?)%}', r'^=+ (.*?)$']    
        title = extract_data_from_file(path, regex)
        title_id = extract_title_id_from_file(path, title)
        
        entry['title'] = clean_string(title)
        title_id = generate_unique_id(title_id, sitemap)
        entry[title_id] = title_id
        sitemap[title_id] = {'title':title, 'path':entry['path']}
    
    return sitemap

def export_structure(template_files, structure_path, root_path):

    structure_to_export = []
    for entry in template_files:
        dir_path = entry['path'].path_local
        file_path = entry['path'].filename.replace('.html.j2','.html')

#        level_toc = 0
#        hide_toc = False
#        if 'extra-config' in entry:
#            if 'level-toc' in entry['extra-config']:
#                level_toc = entry['extra-config']['level-toc']
#            if 'hide-toc' in entry['extra-config']:
#                hide_toc = entry['extra-config']['hide-toc']
#        structure_to_export.append({'dir':dir_path,'filename':file_path,'level':entry['path'].level,'title':entry['title'], 'level_toc':level_toc, 'hide_toc':hide_toc})
        
        structure = {'dir':dir_path,'filename':file_path,'level':entry['path'].level,'title':entry['title']}
        if 'extra-config' in entry:
            for extra_element in entry['extra-config']:
                structure[extra_element] = entry['extra-config'][extra_element]
        structure_to_export.append(structure)



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

def export_sitemap(sitemap, dir_sitemap, meta):

    if not os.path.isdir(dir_sitemap):
        os.mkdir(dir_sitemap)

    for id in sitemap:
        path_dest = '../'+sitemap[id]['path'].filepath_local().replace('.html.j2','.html')

        with open(dir_sitemap+id+'.html', 'w') as fid:
            fid.write(f'<html><head><meta http-equiv="refresh" content="0; url={path_dest}"></head></html>')
