import os
import re
import json
from collections import Counter

from lib import source_scan
from lib.source_map import strip as strip_markers
from lib.structure import built_pages, structure, template_path


TITLE_REGEX = re.compile(r'^(=+)(?:\((.*?)\))? (.*?)$', re.MULTILINE)
RAW_MARKERS = re.compile(r'{%-?\s*(?:end)?raw\s*-?%}')


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


def pre_process(meta):
    if not meta.get('title_id', True):          # title_id: false in the configuration
        return
    pages = structure(meta)
    built = {entry['dir'] + entry['filename'] for entry in built_pages(meta)}
    summary_path = meta['site_directory'] + 'structure/title_id.json'
    previous = {}
    if len(built) < len(pages) and os.path.isfile(summary_path):
        with open(summary_path) as fid:        # --only: headings of the other pages
            previous = json.load(fid)

    id_storage = {}
    title_id_summary = {}
    pages_per_directory = Counter(entry['dir'] for entry in pages)

    for entry in pages:
        page_key = entry['dir'] + entry['filename']
        if page_key not in built:
            # Ids are unique in the site: count those of the pages not generated
            title_id_summary[page_key] = previous.get(page_key, [])
            for heading in title_id_summary[page_key]:
                generate_new_id(heading['title'], id_storage)
            continue
        file_path = template_path(meta, entry)

        with open(file_path, 'r') as fid:
            file_content = fid.read()

        title_id_summary[page_key] = []

        # The headings of the text read as LHTML (not in a code block or a
        # comment), each replaced at its own position (identical headings
        # get distinct ids)
        parts, position = [], 0
        for it in source_scan.find(TITLE_REGEX, file_content):
            n = str(len(it.group(1)))
            class_id = file_content[it.start(2):it.end(2)].strip() if it.group(2) is not None else ''
            title = file_content[it.start(3):it.end(3)]

            generated_id = generate_new_id(strip_markers(title), id_storage) + '_l' + str(n)
            if not class_id:
                class_id = '#' + generated_id

            title_id_summary[page_key].append({'level': n, 'title': strip_markers(title), 'id': class_id[1:]})
            parts += [file_content[position:it.start()], '=' * int(n) + '(' + class_id + ') ' + title]
            position = it.end()
        file_content = ''.join(parts) + file_content[position:]

        with open(file_path, 'w') as fid:
            fid.write(file_content)

    meta['headings'] = title_id_summary

    with open(summary_path, 'w') as fid:
        json.dump(title_id_summary, fid, indent=4)

    for entry in pages:
        if entry['dir'] + entry['filename'] not in built:
            continue
        dirname = meta['site_directory'] + entry['dir']
        headings = title_id_summary[entry['dir'] + entry['filename']]
        with open(dirname + entry['filename'] + '.title_id.json', 'w') as fid:
            json.dump(headings, fid, indent=4)
        # Preserve the old URL for a directory index or a single-page folder.
        if entry['filename'] == 'index.html' or pages_per_directory[entry['dir']] == 1:
            with open(dirname + 'title_id.json', 'w') as fid:
                json.dump(headings, fid, indent=4)
