import os
import yaml

from lib.structure import load_structure


menu_path_relative = '/theme/js/menu.js'


def clean_title(input):
    return input.replace('"', '').replace("'", '').strip()


def post_process(meta):
    menu_path = meta['site_directory'] + menu_path_relative
    structure = load_structure(meta['site_directory'])

    toc_txt = '['
    for k, entry in enumerate(structure):
        toc_txt += '{"path":"' + entry['dir'] + entry['filename'] + '",'
        for element in entry:
            if element != 'dir' and element != 'filename':
                toc_txt += '"' + element + '":"' + str(entry[element]) + '", '
        toc_txt += '}'
        if k < len(structure) - 1:
            toc_txt += ', '
    toc_txt += ']'

    with open(menu_path, 'r') as fid:
        menu_content = fid.read()
    menu_content = menu_content.replace('{{TOC}}', toc_txt)
    with open(menu_path, 'w') as fid:
        fid.write(menu_content)
