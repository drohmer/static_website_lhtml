import os
import yaml

from lib.structure import load_structure


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


def post_process(meta):
    structure = load_structure(meta['site_directory'])
    url = structure[0]['dir'] + structure[0]['filename']
    html = create_html_redirection(url)

    redirection_path = meta['site_directory'] + '/index.html'
    with open(redirection_path, 'w') as fid:
        fid.write(html)
