"""The table of contents written into the theme's menu.

A core stage, not a plugin: a project cannot know whether its theme has a
menu, and a theme that has one always needs it filled. The theme says so in
its manifest (lhtml_site/theme.py):

    toc:
      file: 'js/menu.js'      # the file that receives the table of contents
      keys: [duration]        # extra page settings it carries

A theme with no `toc:` gets no menu written, and that is how it says it has
none. The file is read from the theme and written into the site, never read
back from the site: a partial build (--only) does not copy the theme, so the
copy in the site no longer holds the `{{TOC}}` placeholder.
"""
import json
import os

from lhtml_site.structure import DISPLAY_KEYS, page_path, structure
from lhtml_site.theme import of as theme_manifest

PLACEHOLDER = '{{TOC}}'

# The menu is published in the site and read by anyone: only the keys the
# themes display are written (lhtml_site/structure.py, the same list the site's
# structure/ is filtered with), never every setting of a page.
# 'path' is built below; 'children' and 'parent' are built by the theme's JS.
MENU_KEYS = DISPLAY_KEYS


def menu_keys(manifest):
    """The keys written in the menu: those every theme displays, plus the
    ones this theme declares (theme.yaml, `toc: keys:`)."""
    return tuple(MENU_KEYS) + tuple((manifest.get('toc') or {}).get('keys') or ())


def table_of_contents(meta, manifest):
    """The entries of the menu, as the theme's JS reads them."""
    keys = menu_keys(manifest)
    toc = []
    for entry in structure(meta):
        item = {key: str(value) for key, value in entry.items() if key in keys}
        # Keep legacy string values (notably "True" for theme flags), but let
        # JSON escape quotes, backslashes and newlines in metadata and paths.
        item['path'] = page_path(entry)
        toc.append(item)
    return toc


def run(meta):
    """Write the theme's menu file into the site, with the table of contents
    in place of its placeholder. Does nothing for a theme with no menu."""
    manifest = theme_manifest(meta)
    toc_file = (manifest.get('toc') or {}).get('file')
    if not toc_file:
        return
    source = os.path.join(meta['theme'], toc_file)
    target = os.path.join(meta['site_directory'], 'theme', toc_file)
    with open(source, 'r', encoding='utf-8') as fid:
        content = fid.read()
    content = content.replace(PLACEHOLDER, json.dumps(table_of_contents(meta, manifest)))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w', encoding='utf-8', newline='\n') as fid:
        fid.write(content)
