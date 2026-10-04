"""Metadata extraction and sitemap generation utilities."""

import os
import re
import yaml
import json

# Keys of structure.yaml written by the generator (not available to the deck
# metadata nor to the config.yaml of the pages)
STRUCTURE_KEYS = {'path', 'dir', 'filename', 'template', 'level', 'title_id', 'src', 'source', 'occurrence'}

def clean_string(s):
    if s is None:
        return "unknown"
    return re.sub(r"[/'\"()]", '', s).strip()


def extract_data(text, regex):
    """The first match of the first regex of `regex` that matches, or None."""
    for r in regex:
        match = re.findall(re.compile(r, re.DOTALL | re.MULTILINE), text)
        if match:
            return match[0]
    return None


TITLE_ID = re.compile(r'title_id.*?=(.*?)%}', re.DOTALL | re.MULTILINE)


def extract_title_id(text, title):
    match = TITLE_ID.findall(text)
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


def extract_titles(pages):
    """Title of each page (page.title, read in its source) and the sitemap {id: page}."""
    sitemap = {}
    for page in sorted(pages, key=_sitemap_priority):
        title = extract_data(page.text, TITLE_REGEX)
        if title is not None:
            title = RAW_MARKERS.sub('', title)
        title_id = generate_unique_id(extract_title_id(page.text, title), sitemap)
        page.title = clean_string(title)
        sitemap[title_id] = page
    return sitemap


def export_structure(pages, structure_path):
    """structure.yaml (and .json): one entry per page, in order, for the plugins
    and the theme: its title, configuration and deck metadata, its place in the
    site (dir, filename, template, level) and origin (src, source, occurrence).
    Returns the entries."""
    structure_to_export = []
    for page in pages:
        structure = {'title': page.title, **page.settings,
                     'dir': page.site_directory, 'filename': os.path.basename(page.site_html),
                     'template': page.site_template, 'level': page.site_directory.count('/'),
                     'src': str(page.src)}
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
    return structure_to_export


def export_sitemap(sitemap, dir_sitemap):
    os.makedirs(dir_sitemap, exist_ok=True)

    for id, page in sitemap.items():
        with open(dir_sitemap + id + '.html', 'w') as fid:
            fid.write(f'<html><head><meta http-equiv="refresh" content="0; url=../{page.site_html}"></head></html>')
