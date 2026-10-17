"""Metadata extraction and sitemap generation utilities."""

import os
import re
import yaml
import json

from lib import markdown_page, source_scan
from lib.structure import public_entry

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
MARKDOWN_HEADING_REGEX = [r'^ {0,3}#{1,6}[ \t]+(\S[^\n]*)$']


def string_literal(s):
    """The value of a Jinja string literal ('...' or "..."), or s stripped
    when it is not one."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in '\'"':
        inner = s[1:-1]
        return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t'}.get(m.group(1), m.group(1)), inner) \
            if '\\' in inner else inner
    return s


def extract_title(source, macros=None):
    """Title of a page: its tocTitle or pageTitle (a Jinja string), or its
    first heading (`= Title`, `# Title` in Markdown), as written (apostrophes,
    parentheses and slashes kept); None without any. The first heading of an
    LHTML page is that of its document tree (source_scan.lhtml_headings, with
    the macros of the design: the tree of the page the other scanners read)."""
    source = source_scan.scan(source)
    title = extract_data(source, TITLE_SET_REGEX)
    if title is not None:
        return string_literal(RAW_MARKERS.sub('', title))
    if source.markup != 'markdown':
        found = source_scan.lhtml_headings(source, macros)
        return RAW_MARKERS.sub('', found[0][4]).strip() if found else None
    title = extract_data(source, MARKDOWN_HEADING_REGEX)
    if title is not None:                                           # as headings.py reads it
        title = re.sub(r'[ \t]+\{:[ \t]*#[^\s}]+[ \t]*\}[ \t]*$', '', ' ' + title)
        title = markdown_page.plain(re.sub(r'[ \t]+#+[ \t]*$', '', title))
    return RAW_MARKERS.sub('', title).strip() if title is not None else None


def extract_titles(pages, macros=None):
    """Title of each page (page.title, read in its source) and the sitemap {id: page}."""
    sitemap = {}
    for page in sorted(pages, key=_sitemap_priority):
        title = extract_title(page.scan, macros)
        title_id = generate_unique_id(extract_title_id(page.scan, title), sitemap)
        page.title = title if title is not None else 'unknown'
        sitemap[title_id] = page
    return sitemap


def export_structure(pages, structure_path, public_keys=()):
    """structure.yaml (and .json): one entry per page, in order, for the
    plugins and the theme: its title, its place in the site (dir, filename,
    template, level) and its origin (source, occurrence). The files written
    into the site hold the public keys only (lib/structure.py); the entries
    returned, which the build uses, also hold the settings of the page and
    `src`, the path of its source."""
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

    # Written into the site: the public part of each entry (lib/structure.py).
    # The build keeps the whole entry, returned below.
    published = [public_entry(entry, public_keys) for entry in structure_to_export]
    with open(structure_path / 'structure.yaml', 'w', encoding='utf-8', newline='\n') as fid:
        yaml.dump(published, fid)
    with open(structure_path / 'structure.json', 'w', encoding='utf-8', newline='\n') as fid:
        json.dump(published, fid, indent=4, default=str)
    return structure_to_export


def export_sitemap(sitemap, dir_sitemap):
    """A redirection per page, named after its title id; those of the ids a
    page no longer has (a title renamed, --only) are removed."""
    os.makedirs(dir_sitemap, exist_ok=True)
    current = {f'{id}.html' for id in sitemap}
    for name in os.listdir(dir_sitemap):
        if name.endswith('.html') and name not in current:
            os.remove(os.path.join(dir_sitemap, name))

    for id, page in sitemap.items():
        with open(dir_sitemap / f'{id}.html', 'w', encoding='utf-8', newline='\n') as fid:
            fid.write(f'<html><head><meta http-equiv="refresh" content="0; url=../{page.site_html}"></head></html>')
