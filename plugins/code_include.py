"""includeadv::{...}: code of a repository inserted in the pages, between Jinja and LHTML.

    plugin: ['plugins/code_include.py']
    plugin_arg:
      includeadv: {cgp: 'https://github.com/drohmer/cgp'}
"""
import os
import re
import subprocess

from lhtml.tag_parser import extract_bracket_elements


# Directory where the code repositories are cloned, next to the
# configuration (set by prepare)
CODE_DIRECTORY = 'code/'


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
    return content.strip(' ')


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


def research_file(arg, context):
    file_to_research = arg['research_file']
    root_path = CODE_DIRECTORY + arg['root']

    candidates = []
    for root, dirs, files in os.walk(root_path):
        for f in files:
            if f == file_to_research:
                candidates.append(root)

    if not candidates:
        context.warning(f'includeadv: no file [{file_to_research}] under [{root_path}]')
        return ''

    # Keep candidate with longest pathname
    best = max(candidates, key=len)
    filepath = best + '/' + file_to_research
    if not os.path.isfile(filepath):
        context.warning(f'includeadv: file not found [{filepath}]')

    # path relative to the code directory
    return filepath[len(CODE_DIRECTORY):]


def extract_first_namespace(content):
    r_code = r'namespace (.*?)\{(.*?)^\}'
    regex_code = re.compile(r_code, re.DOTALL | re.MULTILINE)
    for it in regex_code.finditer(content):
        return it.group(0)
    return ''


def research_line_in_header_files(arg):
    pattern_to_research = arg['research_line']
    all_lines = []
    root_path = CODE_DIRECTORY + arg['root']

    for root, dirs, files in os.walk(root_path):
        local_root = root[len(root_path):]
        for f in files:
            if f.endswith('.hpp'):
                with open(root + '/' + f, 'r', encoding='utf-8') as fid:
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


def prepare(context):
    """The repositories of `plugin_arg: includeadv:` ({name: git URL}), cloned
    into code/ next to the configuration, or updated."""
    global CODE_DIRECTORY
    CODE_DIRECTORY = (context.config_directory / 'code').as_posix() + '/'
    for codename, url in context.options.get('includeadv', {}).items():
        code_dir = CODE_DIRECTORY + codename
        if os.path.isdir(code_dir):
            subprocess.run(['git', 'pull'], cwd=code_dir)
        else:
            os.makedirs(CODE_DIRECTORY, exist_ok=True)
            subprocess.run(['git', 'clone', url], cwd=CODE_DIRECTORY)


def mid_process(html, context):
    """Each includeadv::{...} of the page replaced by the code it names:
    filepath alone, the whole file; with research, its first line holding
    the text; research_file, the path of a file under root; research_line,
    the declarations of the headers under root holding the text."""
    parts, prev = [], 0
    for it in re.finditer(r'includeadv::\{.*?\}', html, re.DOTALL):
        arg_includeadv = analyse_includeadv_match(html, it)

        include_file_content = None
        if 'filepath' in arg_includeadv:
            with open(CODE_DIRECTORY + arg_includeadv['filepath'], 'r', encoding='utf-8') as fid:
                include_file_content = fid.read()

        if 'filepath' in arg_includeadv and not {'research', 'research_file', 'research_line'} & set(arg_includeadv):
            parts += [html[prev:it.start()], include_file_content]

        if 'research' in arg_includeadv:
            if include_file_content is None:
                context.warning("includeadv: 'research' needs a 'filepath'")
                continue
            matching_line = extract_first_matching_line(include_file_content, arg_includeadv['research'])
            if matching_line is None:
                context.warning(f"includeadv: could not extract line [{arg_includeadv['research']}]")
                continue
            parts += [html[prev:it.start()], clean_include(matching_line)]

        if 'research_file' in arg_includeadv:
            filepath = research_file(arg_includeadv, context)
            parts += [html[prev:it.start()], filepath[len(arg_includeadv['root']):]]

        if 'research_line' in arg_includeadv:
            parts += [html[prev:it.start()], research_line_in_header_files(arg_includeadv)]

        prev = it.end()
    parts.append(html[prev:])
    return ''.join(parts)
