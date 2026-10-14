import os
import json

from lib.structure import DISPLAY_KEYS, structure


menu_path_relative = '/theme/js/menu.js'

# The menu is published in the site and read by anyone: only the keys the
# themes display are written (lib/structure.py, the same list the site's
# structure/ is filtered with), never every setting of a page.
# 'path' is built below; 'children' and 'parent' are built by the theme's JS.
MENU_KEYS = DISPLAY_KEYS


def menu_keys(meta):
    """The keys written in the menu: those of the bundled themes, plus the
    ones a custom theme declares (plugin_arg: menu: keys: [...])."""
    extra = ((meta.get('plugin_arg') or {}).get('menu') or {}).get('keys') or []
    if isinstance(extra, str):
        extra = [extra]
    return tuple(MENU_KEYS) + tuple(extra)


def post_process(meta):
    menu_path = meta['site_directory'] + menu_path_relative

    # Keep legacy string values (notably "True" for theme flags), but let
    # JSON escape quotes, backslashes and newlines in metadata and paths.
    keys = menu_keys(meta)
    toc = []
    for entry in structure(meta):
        item = {key: str(value) for key, value in entry.items() if key in keys}
        item['path'] = entry['dir'] + entry['filename']
        toc.append(item)
    toc_txt = json.dumps(toc)

    # Start from the template of the theme: the menu of the site no longer
    # contains the TOC placeholder (--only)
    template_path = meta['theme'].rstrip('/') + menu_path_relative[len('/theme'):]
    with open(template_path, 'r', encoding='utf-8') as fid:
        menu_content = fid.read()
    menu_content = menu_content.replace('{{TOC}}', toc_txt)
    os.makedirs(os.path.dirname(menu_path), exist_ok=True)
    with open(menu_path, 'w', encoding='utf-8') as fid:
        fid.write(menu_content)
