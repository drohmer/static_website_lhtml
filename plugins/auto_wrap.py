import os
import yaml

from lib.structure import load_structure

template_auto_wrap = '''
{{% set pageTitle = '{title}' %}}
{{% set tocTitle = '{title}' %}}

{{% extends "theme/template/base.html" %}}

{{% block content %}}

{content}

{{% endblock %}}
'''


def pre_process(meta):
    structure = load_structure(meta['site_directory'])

    for entry in structure:
        file_path = meta['site_directory'] + entry['dir'] + entry['filename'].replace('.html', '.html.j2')

        with open(file_path, 'r') as fid:
            file_content = fid.read()

        # Do not change files that are already wrapped
        if '{% block content %}' not in file_content:
            content = template_auto_wrap.format(title=entry['title'], content=file_content)
            with open(file_path, 'w') as fid:
                fid.write(content)
