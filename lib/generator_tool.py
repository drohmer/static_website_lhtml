"""Metadata extraction and sitemap generation utilities."""

import os
import re
import yaml
import json

from lib import source_scan

# Keys of structure.yaml written by the generator (not available to the deck
# metadata nor to the config.yaml of the pages)
STRUCTURE_KEYS = {'path', 'dir', 'filename', 'template', 'level', 'title_id', 'src', 'source', 'occurrence'}

def clean_string(s):
    if s is None:
        return "unknown"
    return re.sub(r"[/'\"()]", '', s).strip()


def extract_data(source, regex):
    """The first group of the first match of the first regex of `regex` that
    matches in the text read as LHTML (not in a code block or a comment) of
    `source` (a text or a source_scan.Scan), as written; or None."""
    source = source_scan.scan(source)
    for r in regex:
        found = source_scan.find(re.compile(r, re.DOTALL | re.MULTILINE), source)
        if found:
            return source.text[found[0].start(1):found[0].end(1)]
    return None


TITLE_ID = [r'title_id.*?=(.*?)%}']


def extract_title_id(source, title):
    data = extract_data(source, TITLE_ID)
    return clean_string(data if data is not None else title).replace(' ', '_').replace('#', '').lower()


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
TITLE_SET_REGEX = [r'tocTitle.*?=(.*?)%}', r'pageTitle.*?=(.*?)%}']
TITLE_HEADING_REGEX = [r'^=+ (.*?)$']


def string_literal(s):
    """The value of a Jinja string literal ('...' or "..."), or s stripped
    when it is not one."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in '\'"':
        quote, inner = s[0], s[1:-1]
        return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t'}.get(m.group(1), m.group(1)), inner) \
            if '\\' in inner else inner
    return s


def extract_title(source):
    """Title of a page: its tocTitle or pageTitle (a Jinja string), or its
    first heading `= Title`, as written (apostrophes, parentheses and slashes
    kept); None without any."""
    title = extract_data(source, TITLE_SET_REGEX)
    if title is not None:
        return string_literal(RAW_MARKERS.sub('', title))
    title = extract_data(source, TITLE_HEADING_REGEX)
    return RAW_MARKERS.sub('', title).strip() if title is not None else None


def extract_titles(pages):
    """Title of each page (page.title, read in its source) and the sitemap {id: page}."""
    sitemap = {}
    for page in sorted(pages, key=_sitemap_priority):
        title = extract_title(page.scan)
        title_id = generate_unique_id(extract_title_id(page.scan, title), sitemap)
        page.title = title if title is not None else 'unknown'
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
