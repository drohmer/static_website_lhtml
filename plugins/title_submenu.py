import os
import re
import json
import shutil
from collections import Counter

from lib.structure import load_structure, template_path


TITLE_REGEX = re.compile(r'^(=+)(?:\((.*?)\))? (.*?)$', re.MULTILINE)


def generate_new_id(text, id_storage):
    """Return a unique id for a heading text.

    Same scheme as before the refactoring, so that existing links keep
    working: lower case, spaces and '-' become '_', ',.:()' are removed,
    truncated to N_max characters. Characters that are unsafe in an HTML
    attribute or a URL fragment (< > " & ` and whitespace) are removed too.
    A repeated id gets the suffix _id2, _id3, ...
    """
    N_max = 20
    text_id = text.lower().replace(' ', '_').replace('-', '_')
    text_id = re.sub(r'[,.:()<>"&`\s]', '', text_id)
    text_id = text_id[:N_max]

    if text_id in id_storage:
        id_storage[text_id] += 1
        return text_id + '_id' + str(id_storage[text_id])
    id_storage[text_id] = 1
    return text_id


def pre_process(meta):
    structure = load_structure(meta['site_directory'])

    id_storage = {}
    title_id_summary = {}
    pages_per_directory = Counter(entry['dir'] for entry in structure)

    for entry in structure:
        file_path = template_path(meta, entry)

        with open(file_path, 'r') as fid:
            file_content = fid.read()

        page_key = entry['dir'] + entry['filename']
        title_id_summary[page_key] = []

        def add_id(it, page=page_key):
            n = str(len(it.group(1)))
            class_id = (it.group(2) or '').strip()
            title = it.group(3)

            generated_id = generate_new_id(title, id_storage) + '_l' + str(n)
            if not class_id:
                class_id = '#' + generated_id

            title_id_summary[page].append({'level': n, 'title': title, 'id': class_id[1:]})
            # Each heading is replaced at its own position (identical
            # headings get distinct ids)
            return '=' * int(n) + '(' + class_id + ') ' + title

        file_content = TITLE_REGEX.sub(add_id, file_content)

        with open(file_path, 'w') as fid:
            fid.write(file_content)

    meta['title_id'] = title_id_summary

    with open(meta['site_directory'] + 'structure/title_id.json', 'w') as fid:
        json.dump(title_id_summary, fid, indent=4)

    for entry in structure:
        dirname = meta['site_directory'] + entry['dir']
        headings = title_id_summary[entry['dir'] + entry['filename']]
        with open(dirname + entry['filename'] + '.title_id.json', 'w') as fid:
            json.dump(headings, fid, indent=4)
        # Preserve the old URL for a directory index or a single-page folder.
        if entry['filename'] == 'index.html' or pages_per_directory[entry['dir']] == 1:
            with open(dirname + 'title_id.json', 'w') as fid:
                json.dump(headings, fid, indent=4)

    # A light rebuild must also update the reader for the new per-page files.
    if getattr(meta.get('args'), 'light', False):
        source = os.path.join(meta['theme'], 'js/title_id.js')
        target = os.path.join(meta['site_directory'], 'theme/js/title_id.js')
        if os.path.isfile(source):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
