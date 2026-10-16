"""The index of a site that has none: a redirection to its first page.

A core stage, not a plugin: a site whose root has no index.html is broken,
and nothing a project could say would make that acceptable. A hand-written
index.html in the sources, or a page that already builds one, takes
precedence and the stage does nothing.
"""
import os

from lib.structure import structure


def create_html_redirection(url):
    return f'''
<html>
    <head>
        <meta http-equiv="refresh" content="0; url={url}" />
    </head>
    <body>
        Redirection to <a href="{url}">{url}</a>
    </body>
</html>
'''


def run(meta):
    pages = structure(meta)
    if not pages or any(os.path.normpath(entry['dir'] + entry['filename']) == 'index.html'
                        for entry in pages):
        return
    # A hand-written HTML homepage also takes precedence over a redirect.
    if os.path.isfile(os.path.join(meta['source_directory'], 'index.html')):
        return
    url = pages[0]['dir'] + pages[0]['filename']
    html = create_html_redirection(url)

    redirection_path = meta['site_directory'] + '/index.html'
    with open(redirection_path, 'w', encoding='utf-8') as fid:
        fid.write(html)
