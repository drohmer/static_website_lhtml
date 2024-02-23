import sys
import os
import re
import json
import yaml

sys.path.append(os.path.dirname(os.path.abspath(__file__))+'/../lib')
import filesystem

sys.path.append(os.path.dirname(os.path.abspath(__file__))+'/../lib/lhtml/src/lhtmlLib/')
import element_extract

def load_structure(site_directory):
    structure_path = site_directory+'/structure/structure.yaml'
    with open(structure_path) as fid:
        structure = yaml.load(fid, Loader=yaml.loader.SafeLoader)
    return structure


def split_group_with_quote(text, separator):

    group = []
    tmp = ''
    mode_quote = False
    N = len(text)
    for k in range(N):
        c = text[k]
        
        if c=="'" or c=='"':
            if mode_quote==False:
                mode_quote=True
            elif mode_quote==True:
                mode_quote=False
            tmp += c
            continue

        if mode_quote==True:
            tmp += c
        else:
            if c == separator:
                group.append(tmp)
                tmp = ''
                continue
            else:
                tmp += c
    group.append(tmp)

    return group

def extract_first_matching_line(text_content, expression):
    lines = text_content.split('\n')
    for line in lines:
        if line.find(expression)!=-1:
            return line



def analyse_includeadv_match(file_content, it):
    element = element_extract.extract_bracket_elements(file_content, it.span()[0]+len("includeadv::"))
    arg_includeadv = {}
    tokens = split_group_with_quote(element['{}'],",")
    for token in tokens:
        k,v = token.split(':')
        k = k.replace(' ','')
        if v.startswith("'") or v.startswith('"'):
            v = v[1:-1]
        arg_includeadv[k]=v

    return arg_includeadv

def remove_template(content):
    if content.startswith('template <'):
        end_template = content.find('>')
        content = content[end_template+1:]
    return content

def remove_trailing_space(content):
    content = content.replace('\t','  ')
    while content.startswith(' ') and len(content)>0:
        content = content[1:]
    while content.endswith(' ') and len(content)>0:
        content = content[:-1]
    return content

def remove_const_ref(content):
    content = content.replace('const&','')
    return content

def remove_inline(content):
    content = content.replace('inline ','')
    return content

def clean_include(content):
    content = remove_trailing_space(content)
    content = remove_template(content)
    content = remove_const_ref(content)
    content = remove_inline(content)
    content = remove_trailing_space(content)
    return content


def research_file(arg):
    file_to_research = arg['research_file']

    root_path = 'code/'+arg['root']

    candidates = []
    for root,firs,files in os.walk(root_path):
        for f in files:
            if f==file_to_research:
                candidates.append(root)

    if len(candidates)==0:
        print('Warning could not find any candidate for file ['+file_to_research+']')
        return ''
    
    # keep the candidate with longest pathname
    max_length = 0
    k_ideal = 0
    for k,candidate in enumerate(candidates):
        if len(candidate)>max_length:
            max_length = len(candidate)
            k_ideal = k

    filepath = candidates[k_ideal]+'/'+file_to_research
    if not os.path.isfile(filepath):
        print('Warning ideal file not found ['+filepath+']')

    return filepath[5:]

def extract_first_namespace(content):
    r_code = r'namespace (.*?)\{(.*?)^\}'
    regex_code = re.compile(r_code,  re.DOTALL | re.MULTILINE)
    match = re.finditer(regex_code, content)
        
    for it in match:
        return it.group(0)
    return ''        

def research_line_in_header_files(arg):
    pattern_to_research = arg['research_line']
    all_lines = []

    root_path = 'code/'+arg['root']

    candidates = []
    for root,firs,files in os.walk(root_path):
        local_root = root[len(root_path):]
        for f in files:
            if f.endswith('.hpp'):
                with open(root+'/'+f,'r') as fid:
                    content = fid.read()
                
                
                content = extract_first_namespace(content)
                if len(content)>0:
                    lines = content.split('\n')

                    for line in lines:
                        if line.find(pattern_to_research)!=-1:
                            line_txt = clean_include(line)
                            if line_txt.endswith(';') and not line_txt.startswith('//'):
                                all_lines.append('// file '+local_root+'/'+f+'\n')
                                all_lines.append(line_txt+'\n\n')
    
    txt = ''
    for l in all_lines:
        txt += clean_include(l)
    return txt


def mid_process(meta):

    # load structure
    structure = load_structure(meta['site_directory'])


    # code to download
    if 'plugin_arg' in meta:
        if 'includeadv' in meta['plugin_arg']:
            for codename in meta['plugin_arg']['includeadv']:
                url = meta['plugin_arg']['includeadv'][codename]
                if os.path.isdir('code/'):
                    os.system(f'cd code/{codename}/; git pull')
                else:
                    os.system(f'mkdir -p code/{codename}/')
                    os.system(f'cd code/; git clone {url}')
    

    for entry in structure:
        dirname = meta['site_directory'] + entry['dir']
        file_path = meta['site_directory'] + entry['dir'] + entry['filename']
        

        with open(file_path,'r') as fid:
            file_content = fid.read()

        
            r_code = r'includeadv::{.*?}'
            regex_code = re.compile(r_code,  re.DOTALL | re.MULTILINE)
            match = re.finditer(regex_code, file_content)


            new_text = ''
            index_previous = 0
            for it in match:
                arg_includeadv = analyse_includeadv_match(file_content, it)

                if 'filepath' in arg_includeadv:
                    include_filepath = 'code/'+arg_includeadv['filepath']
                            
                    with open(include_filepath,'r') as fid:
                        include_file_content = fid.read()
                
                if 'research' in arg_includeadv:
                    matching_line = extract_first_matching_line(include_file_content, arg_includeadv['research'])
                    if matching_line==None:
                        print("\nWarning, could not extract line ["+arg_includeadv['research']+']')
                        continue
                    matching_line = clean_include(matching_line)
                    new_text += file_content[index_previous:it.span()[0]]
                    new_text += matching_line

                if 'research_file' in arg_includeadv:
                    filepath = research_file(arg_includeadv)
                    filepath_local = filepath[len(arg_includeadv['root']):]
                    new_text += file_content[index_previous:it.span()[0]]
                    new_text += filepath_local
                
                if 'research_line' in arg_includeadv:
                    lines = research_line_in_header_files(arg_includeadv)
                    new_text += file_content[index_previous:it.span()[0]]
                    new_text += lines

                # research_regex = arg_include['research']
                # r_code = r'^.(.*?)'+research_regex+'(.*?).$'
                # regex_code = re.compile(r_code,  re.DOTALL | re.MULTILINE)
                # match = re.finditer(regex_code, code_content)
                # for it in match:
                #     print('MATCH!')
                #     print(it.group(1))
                
                

                index_previous = it.span()[1]

            new_text += file_content[index_previous:]

        with open(file_path,'w') as fid:
            fid.write(new_text)

        


    #os.system('rm -rf code')        
        