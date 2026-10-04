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


def post_process(meta):
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
    with open(redirection_path, 'w') as fid:
        fid.write(html)
