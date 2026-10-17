"""Heading ids and the per-page summary of the headings (title_id.json).

A core stage, not a plugin: every page of a site needs stable ids for its
headings, and the theme's menu reads the summary. `title_id: false` in the
configuration turns it off for a project that writes its own ids.

The headings of an LHTML page are those of its document tree
(lhtml.parse, on the template before Jinja: Jinja is opaque to LHTML), so
that a heading is exactly what LHTML makes one (not in a code block, a
comment, raw HTML...); those of a Markdown page are found in the text read
as Markdown (source_scan).
"""
import os
import re
import json
from collections import Counter

from lib import markdown_page, source_scan
from lib.source_map import strip as strip_markers
from lib.generator_tool import RAW_MARKERS
from lib.pages import markup
from lib.structure import built_pages, page_path, structure, template_path


# The start of an LHTML heading the tree found, to read its attributes as
# written ((.c #id), Jinja included) and where its title starts
HEADING_START = re.compile(r'(=+)(?:\((.*?)\))? ')
# A Markdown heading (ATX), found in the text read as Markdown, then read on
# its line as written - a code span or mathematics ending it is blank in the
# masked text. An id written by hand or by this stage: # Title {: #id}
MARKDOWN_TITLE = re.compile(r'^ {0,3}(#{1,6})[ \t]+\S.*$', re.MULTILINE)
MARKDOWN_ID = re.compile(r'[ \t]+\{:[ \t]*(#[^\s}]+)[ \t]*\}[ \t]*$')
MARKDOWN_CLOSING = re.compile(r'[ \t]+#+[ \t]*$')       # # Title ## : the closing sequence


def generate_new_id(text, id_storage):
    """Return a unique id for a heading text.

    Same scheme as before the refactoring, so that existing links keep
    working: lower case, spaces and '-' become '_', ',.:()' are removed,
    truncated to N_max characters. Characters that are unsafe in an HTML
    attribute or a URL fragment (< > " & ` and whitespace) are removed too,
    as the Jinja markers ({% raw %}, braces, %) of a title.
    A repeated id gets the suffix _id2, _id3, ...
    """
    N_max = 20
    text_id = RAW_MARKERS.sub('', text).lower().replace(' ', '_').replace('-', '_')
    text_id = re.sub(r'[,.:()<>"&`\s{}%]', '', text_id)
    text_id = text_id[:N_max]

    if text_id in id_storage:
        id_storage[text_id] += 1
        return text_id + '_id' + str(id_storage[text_id])
    id_storage[text_id] = 1
    return text_id


def lhtml_headings(text):
    """The headings of an LHTML page, those of its document tree: (start,
    end, level, attributes as written, title as written). A page that LHTML
    refuses has none here: its run reports why."""
    document = source_scan.document(text)
    found = []
    for node in document.walk() if document else ():
        if node.kind == 'Heading':
            start, end = node.span
            m = HEADING_START.match(text, start)
            found.append((start, end, node.level, (m.group(2) or '').strip(), text[m.end():end]))
    return found


def markdown_headings(text):
    """The headings of a Markdown page, as lhtml_headings."""
    found = []
    for it in source_scan.find(MARKDOWN_TITLE, source_scan.Scan(text, 'markdown')):
        level = len(it.group(1))
        line = text[it.start():it.end()].rstrip()
        written = line[line.index('#') + level:].strip()
        found_id = MARKDOWN_ID.search(' ' + written)
        class_id = found_id.group(1) if found_id else ''
        written = (' ' + written)[:found_id.start()].strip() if found_id else written
        written = MARKDOWN_CLOSING.sub('', ' ' + written).strip()
        found.append((it.start(), it.end(), level, class_id, written))
    return found


def run(meta):
    if not meta.get('title_id', True):          # title_id: false in the configuration
        return
    pages = structure(meta)
    built = {page_path(entry) for entry in built_pages(meta)}
    summary_path = meta['site_directory'] / 'structure/title_id.json'
    previous = {}
    if len(built) < len(pages) and os.path.isfile(summary_path):
        with open(summary_path, encoding='utf-8') as fid:        # --only: headings of the other pages
            previous = json.load(fid)

    id_storage = {}
    title_id_summary = {}
    pages_per_directory = Counter(entry['dir'] for entry in pages)

    for entry in pages:
        page_key = page_path(entry)
        if page_key not in built:
            # Ids are unique in the site: count those of the pages not generated
            title_id_summary[page_key] = previous.get(page_key, [])
            for heading in title_id_summary[page_key]:
                generate_new_id(heading['title'], id_storage)
            continue
        file_path = template_path(meta, entry)

        with open(file_path, 'r', encoding='utf-8') as fid:
            file_content = fid.read()

        title_id_summary[page_key] = []

        # The headings of the text read as its markup reads it (not in a
        # code block or a comment), each replaced at its own position
        # (identical headings get distinct ids)
        markdown = markup(entry['template']) == 'markdown'
        parts, position = [], 0
        for start, end, level, class_id, written in (markdown_headings if markdown
                                                     else lhtml_headings)(file_content):
            title = markdown_page.plain(written) if markdown else written    # the text, without its marks
            generated_id = generate_new_id(strip_markers(title), id_storage) + '_l' + str(level)
            if not class_id:
                class_id = '#' + generated_id
            title_id_summary[page_key].append({'level': str(level), 'title': strip_markers(title),
                                               'id': class_id[1:]})
            heading = (f"{'#' * level} {written} {{: {class_id}}}" if markdown
                       else '=' * level + '(' + class_id + ') ' + written)
            parts += [file_content[position:start], heading]
            position = end
        file_content = ''.join(parts) + file_content[position:]

        with open(file_path, 'w', encoding='utf-8', newline='\n') as fid:
            fid.write(file_content)

    with open(summary_path, 'w', encoding='utf-8', newline='\n') as fid:
        json.dump(title_id_summary, fid, indent=4)

    for entry in pages:
        if page_path(entry) not in built:
            continue
        dirname = meta['site_directory'] / entry['dir']
        headings = title_id_summary[page_path(entry)]
        with open(dirname / (entry['filename'] + '.title_id.json'), 'w', encoding='utf-8', newline='\n') as fid:
            json.dump(headings, fid, indent=4)
        # Preserve the old URL for a directory index or a single-page folder.
        if entry['filename'] == 'index.html' or pages_per_directory[entry['dir']] == 1:
            with open(dirname / 'title_id.json', 'w', encoding='utf-8', newline='\n') as fid:
                json.dump(headings, fid, indent=4)
