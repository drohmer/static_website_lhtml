import sys
import os
import re
import json
import yaml

sys.path.append('lib')
sys.path.append('../lib')
import filesystem

template_auto_wrap = '''
{% set pageTitle = '{{TITLE}}' %}
{% set tocTitle = '{{TITLE}}' %}

{% extends "theme/template/base.html" %}

{% block content %}

{{CONTENT}}

{% endblock %}
'''

def load_structure(site_directory):
    structure_path = site_directory+'/structure/structure.yaml'
    with open(structure_path) as fid:
        structure = yaml.load(fid, Loader=yaml.loader.SafeLoader)
    return structure

def pre_process(meta):

    # load structure
    structure = load_structure(meta['site_directory'])

    for entry in structure:
        file_path = meta['site_directory'] + entry['dir'] + entry['filename'].replace('.html','.html.j2')

        with open(file_path,'r') as fid:
            file_content = fid.read()

        # do not change files that are already wraped
        if file_content.find('{% block content %}')==-1:

            content = template_auto_wrap.replace('{{TITLE}}' ,entry['title']).replace('{{CONTENT}}' ,file_content)

            with open(file_path,'w') as fid:
                fid.write(content)



