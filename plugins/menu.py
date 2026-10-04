import os
import json

from lib.structure import structure


menu_path_relative = '/theme/js/menu.js'


def clean_title(input):
    return input.replace('"', '').replace("'", '').strip()


def post_process(meta):
    menu_path = meta['site_directory'] + menu_path_relative

    # Keep legacy string values (notably "True" for theme flags), but let
    # JSON escape quotes, backslashes and newlines in metadata and paths.
    toc = []
    for entry in structure(meta):
        item = {key: str(value) for key, value in entry.items()
                if key not in ('dir', 'filename', 'template', 'src')}   # src: local path
        item['path'] = entry['dir'] + entry['filename']
        toc.append(item)
    toc_txt = json.dumps(toc)

    # Start from the template of the theme: the menu of the site no longer
    # contains the TOC placeholder (--only)
    template_path = meta['theme'].rstrip('/') + menu_path_relative[len('/theme'):]
    with open(template_path, 'r') as fid:
        menu_content = fid.read()
    menu_content = menu_content.replace('{{TOC}}', toc_txt)
    os.makedirs(os.path.dirname(menu_path), exist_ok=True)
    with open(menu_path, 'w') as fid:
        fid.write(menu_content)
