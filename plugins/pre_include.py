import os
import yaml

from lib.structure import load_structure


def pre_process(meta):
    structure = load_structure(meta['site_directory'])

    files_to_include = meta['plugin_arg']['pre_include']
    content_to_include = []
    for f in files_to_include:
        with open(f, 'r') as fid:
            content_to_include.append(fid.read())

    for entry in structure:
        file_path = meta['site_directory'] + entry['dir'] + entry['filename'].replace('.html', '.html.j2')

        with open(file_path, 'r') as fid:
            file_content = fid.read()

        new_file_content = '\n'.join(content_to_include) + '\n' + file_content

        with open(file_path, 'w') as fid:
            fid.write(new_file_content)
