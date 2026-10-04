"""Metadata extraction and sitemap generation utilities."""

import os
import re
import yaml
import json


def clean_string(s):
    if s is None:
        return "unknown"
    return re.sub(r"[/'\"()]", '', s).strip()


def extract_data_from_file(file, regex):
    with open(file, 'r') as fid:
        file_content = fid.read()

    for r in regex:
        regex_compiled = re.compile(r, re.DOTALL | re.MULTILINE)
        match = re.findall(regex_compiled, file_content)
        if len(match) >= 1:
            return match[0]

    print('Failed to extract data in file ', file)


def extract_title_id_from_file(path, title):
    with open(path, 'r') as fid:
        file_content = fid.read()

    regex = r'title_id.*?=(.*?)%}'
    regex_compiled = re.compile(regex, re.DOTALL | re.MULTILINE)
    match = re.findall(regex_compiled, file_content)
    data = match[0] if match else title
    return clean_string(data).replace(' ', '_').replace('#', '').lower()


def generate_unique_id(title_id, sitemap):
    if title_id in sitemap:
        k = 1
        attempt = title_id
        while attempt in sitemap:
            attempt = title_id + '_' + str(k)
            k += 1
        title_id = attempt
    return title_id


def _sitemap_priority(page):
    """Pages of the project first, in file order, then those of other projects,
    then the repeated pages: adding them to a deck does not change the ids
    (pathTo_<id>) of the pages of the project."""
    return (page.occurrence > 1, page.source.name is not None, page.source.name or '', page.position)


RAW_MARKERS = re.compile(r'{%-?\s*(?:end)?raw\s*-?%}')
TITLE_REGEX = [r'tocTitle.*?=(.*?)%}', r'pageTitle.*?=(.*?)%}', r'^=+ (.*?)$']


def extract_titles(pages, site_directory):
    """Title of each page (page.title) and the sitemap {id: page}."""
    sitemap = {}
    for page in sorted(pages, key=_sitemap_priority):
        path = site_directory + page.site_template
        title = extract_data_from_file(path, TITLE_REGEX)
        if title is not None:
            title = RAW_MARKERS.sub('', title)
        title_id = generate_unique_id(extract_title_id_from_file(path, title), sitemap)
        page.title = clean_string(title)
        sitemap[title_id] = page
    return sitemap


def export_structure(pages, structure_path):
    """structure.yaml (and .json): one entry per page, in order, for the plugins
    and the theme: its place in the site (dir, filename, template), title,
    level, configuration and deck metadata, and origin (src, source, occurrence)."""
    structure_to_export = []
    for page in pages:
        structure = {'dir': page.site_directory, 'filename': os.path.basename(page.site_html),
                     'template': page.site_template, 'level': page.site_directory.count('/'),
                     'title': page.title, **page.config, **page.meta, 'src': str(page.src)}
        if page.source.name:
            structure['source'] = page.source.name
        if page.occurrence > 1:
            structure['occurrence'] = page.occurrence
        structure_to_export.append(structure)

    os.makedirs(structure_path, exist_ok=True)

    with open(structure_path + 'structure.yaml', 'w') as fid:
        yaml.dump(structure_to_export, fid)
    with open(structure_path + 'structure.json', 'w') as fid:
        json.dump(structure_to_export, fid, indent=4, default=str)


def export_sitemap(sitemap, dir_sitemap):
    os.makedirs(dir_sitemap, exist_ok=True)

    for id, page in sitemap.items():
        with open(dir_sitemap + id + '.html', 'w') as fid:
            fid.write(f'<html><head><meta http-equiv="refresh" content="0; url=../{page.site_html}"></head></html>')
