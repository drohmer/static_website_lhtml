"""Heading ids.

A core stage, not a plugin: every page of a site needs stable ids for its
headings, so that a link can point to one, and the theme webpage-frame lists
them in its "Page content" column (read in the page, js/title_id.js).
`title_id: false` in the configuration turns it off for a project that
writes its own ids.

The headings of an LHTML page are those of its document tree
(lhtml.parse, on the template before Jinja: Jinja is opaque to LHTML), so
that a heading is exactly what LHTML makes one (not in a code block, a
comment, raw HTML...); those of a Markdown page are found in the text read
as Markdown (source_scan).

A heading written as text gets its id here, from that text. A heading whose
text comes from Jinja (`= {{ PARTIES[current - 1][0] }}`) has no text yet:
its id is written as a Jinja filter on that text (JINJA_FILTER), so that it
is computed from the heading as rendered, with the same scheme - each
occurrence of a template reused with params, or each heading of a loop,
gets its own.

The ids of the headings written as text are unique in the site; a --only
build counts those of the pages it does not generate, recorded by the
previous build in .verification/ (build state, not published: HEADINGS).
"""
import re
import json
from pathlib import Path

from lhtml_site import markdown_page, source_scan
from lhtml_site.source_scan import lhtml_headings
from lhtml_site.source_map import strip as strip_markers
from lhtml_site.generator_tool import RAW_MARKERS
from lhtml_site.pages import markup
from lhtml_site.structure import built_pages, page_path, structure, template_path

# The headings of each page, as text: {page: [{level, title, id}]}, under
# .verification/<scope>/ next to the dependency store. Sites built up to 3.0
# kept it in the site (structure/title_id.json): read once, if this one is missing.
HEADINGS = 'headings.json'
LEGACY_SUMMARY = 'structure/title_id.json'

# The Jinja filter giving its id to a heading whose text comes from Jinja
# (registered in the environment of the pages, lhtml_site/generate.py)
JINJA_FILTER = 'lhtml_heading_id'

# Jinja in a heading: an expression, a statement or a comment, outside
# {% raw %} ... {% endraw %} (whose text is the heading's, as written)
JINJA = re.compile(r'{[{%#]')
RAW_BLOCK = re.compile(r'{%-?\s*raw\s*-?%}.*?{%-?\s*endraw\s*-?%}', re.DOTALL)
WRITTEN_ID = re.compile(r'#([^\s.#]+)')


# A Markdown heading (ATX), found in the text read as Markdown, then read on
# its line as written - a code span or mathematics ending it is blank in the
# masked text. An id written by hand or by this stage: # Title {: #id}
MARKDOWN_TITLE = re.compile(r'^ {0,3}(#{1,6})[ \t]+\S.*$', re.MULTILINE)
MARKDOWN_ID = re.compile(r'[ \t]+\{:[ \t]*(#[^\s}]+)[ \t]*\}[ \t]*$')
MARKDOWN_CLOSING = re.compile(r'[ \t]+#+[ \t]*$')       # # Title ## : the closing sequence


def generate_new_id(text, id_storage):
    """Return a unique id for a heading text.

    The scheme of the last copied generator (title_submenu.py, April 2026),
    so that links into the sites it built keep working: lower case, each of
    ' -,.:()' becomes '_', then '__' becomes '_' (one pass: ' - ' gives
    '__'), truncated to N_max characters. Two fixes: characters that are
    unsafe in an HTML attribute or a URL fragment (< > " & ` and whitespace
    other than a space) are removed first, as the Jinja markers
    ({% raw %}, braces, %) of a title; and a repeated id gets the suffix
    _id2, _id3, ... (the third one was _id2 again). Sites built before
    April 2026 removed ',.:()' instead: their headings with these
    characters or ' - ' have other ids.
    """
    N_max = 20
    text_id = re.sub(r'[<>"&`{}%]|[^\S ]', '', RAW_MARKERS.sub('', text).lower())
    text_id = re.sub(r'[-,.:() ]', '_', text_id).replace('__', '_')
    text_id = text_id[:N_max]

    if text_id in id_storage:
        id_storage[text_id] += 1
        return text_id + '_id' + str(id_storage[text_id])
    id_storage[text_id] = 1
    return text_id


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


def has_jinja(text):
    """Whether the text of a heading comes (in part) from Jinja."""
    return bool(JINJA.search(RAW_BLOCK.sub('', text)))


def summary_path(meta):
    """The headings of the previous build (build state, not published)."""
    return Path(meta['config_directory']) / '.verification' / (meta.get('build_scope') or '') / HEADINGS


def previous_summary(meta):
    """The headings recorded by the previous build: {page: [...]}, {} if none."""
    for path in (summary_path(meta), Path(meta['site_directory']) / LEGACY_SUMMARY):
        try:
            with open(path, encoding='utf-8') as fid:
                value = json.load(fid)
            if isinstance(value, dict):
                return value
        except (OSError, ValueError):
            continue
    return {}


def page_unique_id(text, level, taken):
    """The id of a heading rendered by Jinja: the scheme of generate_new_id,
    unique among the ids of its page (`taken`, completed)."""
    base, k = generate_new_id(text, {}), 1
    candidate = f'{base}_l{level}'
    while candidate in taken:
        k += 1
        candidate = f'{base}_id{k}_l{level}'
    taken.add(candidate)
    return candidate


def jinja_filter(meta):
    """The filter JINJA_FILTER: the id of a heading from its text as Jinja
    rendered it, unique in its page (the ids of the page are those this
    stage wrote, meta['heading_ids'])."""
    def heading_id(text, level, page, is_markdown=False):
        text = strip_markers(str(text))
        if is_markdown:
            text = markdown_page.plain(text)
        return page_unique_id(text, level, meta.setdefault('heading_ids', {}).setdefault(page, set()))
    return heading_id


def run(meta):
    meta['heading_ids'], meta['heading_summary'] = {}, None
    if not meta.get('title_id', True):          # title_id: false in the configuration
        return
    pages = structure(meta)
    built = {page_path(entry) for entry in built_pages(meta)}
    previous = previous_summary(meta) if len(built) < len(pages) else {}   # --only: the other pages

    id_storage = {}
    summary = {}

    for entry in pages:
        page_key = page_path(entry)
        if page_key not in built:
            # Ids are unique in the site: count those of the pages not generated
            summary[page_key] = previous.get(page_key, [])
            for heading in summary[page_key]:
                generate_new_id(heading['title'], id_storage)
            continue
        file_path = template_path(meta, entry)

        with open(file_path, 'r', encoding='utf-8') as fid:
            file_content = fid.read()

        summary[page_key] = []
        taken = meta['heading_ids'][page_key] = set()

        # The headings of the text read as its markup reads it (not in a
        # code block or a comment), each replaced at its own position
        # (identical headings get distinct ids)
        markdown = markup(entry['template']) == 'markdown'
        parts, position = [], 0
        found = (markdown_headings(file_content) if markdown
                 else lhtml_headings(file_content, meta.get('macros')))
        for start, end, level, class_id, written in found:
            title = strip_markers(markdown_page.plain(written) if markdown else written)
            # Every heading counts, as before 3.1: the ids of the headings
            # written as text stay those of the sites already published
            generated_id = generate_new_id(title, id_storage) + '_l' + str(level)
            jinja = has_jinja(written)
            summary[page_key].append({'level': str(level), 'title': title,
                                      'id': None if jinja and not class_id else (class_id[1:] if class_id else generated_id)})
            if class_id:                        # written by hand: kept as written
                taken.update(WRITTEN_ID.findall(class_id))
                continue
            if jinja:
                # Its text is known once Jinja has rendered it: so is its id
                generated_id = ('{% filter ' + JINJA_FILTER + '(' + str(level) + ', ' + json.dumps(page_key)
                                + (', true' if markdown else '') + ') %}' + written + '{% endfilter %}')
            else:
                taken.add(generated_id)
            heading = (f"{'#' * level} {written} {{: #{generated_id}}}" if markdown
                       else '=' * level + '(#' + generated_id + ') ' + written)
            parts += [file_content[position:start], heading]
            position = end
        file_content = ''.join(parts) + file_content[position:]

        with open(file_path, 'w', encoding='utf-8', newline='\n') as fid:
            fid.write(file_content)

    meta['heading_summary'] = summary


def save(meta):
    """Record the headings of a build that succeeded, for the next --only
    (a failed build leaves the previous site, and its record, in place)."""
    if meta.get('heading_summary') is None:
        return
    path = summary_path(meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fid:
        json.dump(meta['heading_summary'], fid, indent=1, ensure_ascii=False)
