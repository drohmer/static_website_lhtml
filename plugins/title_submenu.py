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

def generate_new_id(text, id_storage):

    N_max = 20

    text_id = text.lower().replace(' ','_')
    text_id = text_id.replace('-','_')
    text_id = text_id.replace(',','')
    text_id = text_id.replace('.','')
    text_id = text_id.replace(':','')
    text_id = text_id.replace('(','')
    text_id = text_id.replace(')','')
    if len(text_id)>N_max:
        text_id = text_id[:N_max]

    if text_id in id_storage:
        text_id += '_id'+str(id_storage[text_id]+1)

    id_storage[text_id] = 1
    
    
    return text_id

def pre_process(meta):

    # load structure
    structure = load_structure(meta['site_directory'])

    id_storage = {}
    title_id_summary = {}


    for entry in structure:
        dirname = meta['site_directory'] + entry['dir']
        file_path = meta['site_directory'] + entry['dir'] + entry['filename'].replace('.html','.html.j2')
        

        with open(file_path,'r') as fid:
            file_content = fid.read()
        
        title_id_summary[entry['dir']] = []

        r_title = r'^(=+)\(?(.*?)\)? (.*?)$'
        regex_title = re.compile(r_title,  re.DOTALL | re.MULTILINE)
        match = re.finditer(regex_title, file_content)
        for it in match:
            n = str(len(it.group(1)))
            class_id= it.group(2)
            title = it.group(3)
            
            generated_id = generate_new_id(title, id_storage)+'_l'+str(n)
            if len(class_id)==0:
                class_id = '#'+generated_id

            new_link = '='*int(n) +'('+class_id+') '+title
            file_content = file_content.replace(it.group(0),new_link)

            title_id_summary[entry['dir']].append({'level':n,'title':title,'id':class_id[1:]})


        with open(file_path,'w') as fid:
            fid.write(file_content)
    
    # Store all info in meta
    meta['title_id'] = title_id_summary

    # Save global file in json
    with open(meta['site_directory']+'structure/title_id.json','w') as fid:
        json.dump(title_id_summary, fid, indent=4)
    
    # Save local json file in each directory
    for entry in structure:
        dirname = meta['site_directory'] + entry['dir']
        with open(dirname+'title_id.json','w') as fid:
            json.dump(title_id_summary[entry['dir']], fid, indent=4)