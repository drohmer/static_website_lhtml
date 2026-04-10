import sys
import os
import re
import json
import yaml

sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/../lib')
import filesystem

from lhtml.element_extract import extract_bracket_elements
from lib.structure import load_structure


def split_group_with_quote(text, separator):
    group = []
    tmp = ''
    mode_quote = False
    N = len(text)
    for k in range(N):
        c = text[k]

        if c == "'" or c == '"':
            mode_quote = not mode_quote
            tmp += c
            continue

        if mode_quote:
            tmp += c
        else:
            if c == separator:
                group.append(tmp)
                tmp = ''
            else:
                tmp += c
    group.append(tmp)
    return group


def extract_first_matching_line(text_content, expression):
    for line in text_content.split('\n'):
        if expression in line:
            return line


def analyse_includeadv_match(file_content, it):
    element = extract_bracket_elements(file_content, it.span()[0] + len("includeadv::"))
    arg_includeadv = {}
    tokens = split_group_with_quote(element['{}'], ",")
    for token in tokens:
        k, v = token.split(':')
        k = k.strip()
        if v.startswith("'") or v.startswith('"'):
            v = v[1:-1]
        arg_includeadv[k] = v
    return arg_includeadv


def remove_template(content):
    if content.startswith('template <'):
        end_template = content.find('>')
        content = content[end_template + 1:]
    return content


def remove_trailing_space(content):
    content = content.replace('\t', '  ')
    return content.strip()


def remove_const_ref(content):
    return content.replace('const&', '')


def remove_inline(content):
    return content.replace('inline ', '')


def clean_include(content):
    content = remove_trailing_space(content)
    content = remove_template(content)
    content = remove_const_ref(content)
    content = remove_inline(content)
    return remove_trailing_space(content)


def research_file(arg):
    file_to_research = arg['research_file']
    root_path = 'code/' + arg['root']

    candidates = []
    for root, dirs, files in os.walk(root_path):
        for f in files:
            if f == file_to_research:
                candidates.append(root)

    if not candidates:
        print(f'Warning: could not find any candidate for file [{file_to_research}]')
        return ''

    # Keep candidate with longest pathname
    best = max(candidates, key=len)
    filepath = best + '/' + file_to_research
    if not os.path.isfile(filepath):
        print(f'Warning: ideal file not found [{filepath}]')

    return filepath[5:]


def extract_first_namespace(content):
    r_code = r'namespace (.*?)\{(.*?)^\}'
    regex_code = re.compile(r_code, re.DOTALL | re.MULTILINE)
    for it in regex_code.finditer(content):
        return it.group(0)
    return ''


def research_line_in_header_files(arg):
    pattern_to_research = arg['research_line']
    all_lines = []
    root_path = 'code/' + arg['root']

    for root, dirs, files in os.walk(root_path):
        local_root = root[len(root_path):]
        for f in files:
            if f.endswith('.hpp'):
                with open(root + '/' + f, 'r') as fid:
                    content = fid.read()

                content = extract_first_namespace(content)
                if content:
                    for line in content.split('\n'):
                        if pattern_to_research in line:
                            line_txt = clean_include(line)
                            if line_txt.endswith(';') and not line_txt.startswith('//'):
                                all_lines.append('// file ' + local_root + '/' + f + '\n')
                                all_lines.append(line_txt + '\n\n')

    return ''.join(clean_include(l) for l in all_lines)


def mid_process(meta):
    structure = load_structure(meta['site_directory'])

    # Code to download
    if 'plugin_arg' in meta and 'includeadv' in meta['plugin_arg']:
        for codename in meta['plugin_arg']['includeadv']:
            url = meta['plugin_arg']['includeadv'][codename]
            code_dir = f'code/{codename}'
            if os.path.isdir(code_dir):
                subprocess.run(['git', 'pull'], cwd=code_dir)
            else:
                os.makedirs('code/', exist_ok=True)
                subprocess.run(['git', 'clone', url], cwd='code/')

    for entry in structure:
        file_path = meta['site_directory'] + entry['dir'] + entry['filename']

        with open(file_path, 'r') as fid:
            file_content = fid.read()

        r_code = r'includeadv::\{.*?\}'
        regex_code = re.compile(r_code, re.DOTALL | re.MULTILINE)
        match = regex_code.finditer(file_content)

        parts = []
        prev = 0
        for it in match:
            arg_includeadv = analyse_includeadv_match(file_content, it)

            if 'filepath' in arg_includeadv:
                include_filepath = 'code/' + arg_includeadv['filepath']
                with open(include_filepath, 'r') as fid:
                    include_file_content = fid.read()

            if 'research' in arg_includeadv:
                matching_line = extract_first_matching_line(include_file_content, arg_includeadv['research'])
                if matching_line is None:
                    print(f"\nWarning: could not extract line [{arg_includeadv['research']}]")
                    continue
                parts.append(file_content[prev:it.span()[0]])
                parts.append(clean_include(matching_line))

            if 'research_file' in arg_includeadv:
                filepath = research_file(arg_includeadv)
                filepath_local = filepath[len(arg_includeadv['root']):]
                parts.append(file_content[prev:it.span()[0]])
                parts.append(filepath_local)

            if 'research_line' in arg_includeadv:
                lines = research_line_in_header_files(arg_includeadv)
                parts.append(file_content[prev:it.span()[0]])
                parts.append(lines)

            prev = it.span()[1]

        parts.append(file_content[prev:])

        with open(file_path, 'w') as fid:
            fid.write(''.join(parts))
