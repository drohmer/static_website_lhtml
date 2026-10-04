"""Credits of the images and origin of the slides; what remains to do.

A page declares the credits of its files in its config.yaml (or deck entry):

    credits:
      assets/euler.jpg:
        author: J. E. Handmann, 1753
        source: Wikimedia Commons (File:Leonhard_Euler_-_Jakob_Emanuel_Handmann.jpg)
        license: public domain
        url: https://commons.wikimedia.org/wiki/File:...
      assets/plaque.jpg: Brendan Ward, CC0          # a text is the whole credit
    origin: csc_43043/course_slides/src/08_transformations/02_rotation/01_definition

In a page, `{{ credit('assets/euler.jpg') }}` gives the text of a credit
(`credit:: {{ credit('assets/euler.jpg') }} ::`), and `credits` lists those
of all the pages (a credits slide). Each build writes:
- structure/credits.md: the origin of each page (`origin`, or its project),
  the credits of the images, and the images of the pages without credit;
- structure/todo.md: the planned figures (placeholder::) and slides (deck).
"""
from __future__ import annotations

import os
import re

FIELDS = ('author', 'source', 'license', 'url', 'note')
TEXT_FIELDS = ('author', 'source', 'license')
# files used by a page: img::, video::, videoplay::, src="..." (not the URLs)
FILE_REFERENCE = re.compile(r'(?:img|video|videoplay)::([^\s\[\]:]+)|\bsrc="([^"]+)"')
MEDIA = re.compile(r'\.(png|jpe?g|gif|webp|bmp|tiff?|mp4|webm|mkv|mov)$', re.IGNORECASE)
PLACEHOLDER = re.compile(r'placeholder::(.*?)(?:::|$)')


class CreditsError(ValueError):
    pass


def page_credits(page):
    """{file: {author, source, license, url, note}} of a page (config.yaml,
    then deck entry)."""
    result = {}
    for where, credits in (('config.yaml', page.config.get('credits')), ('deck', page.meta.get('credits'))):
        if credits is None:
            continue
        if not isinstance(credits, dict):
            raise CreditsError(f"{page.label}: 'credits' ({where}) must be a mapping file: credit")
        for file, credit in credits.items():
            if isinstance(credit, str):
                credit = {'author': credit}
            if not isinstance(credit, dict) or set(credit) - set(FIELDS):
                raise CreditsError(f"{page.label}: credit of '{file}' ({where}) must be a text or a mapping "
                                   f"with {', '.join(FIELDS)}")
            result[str(file)] = {k: str(v) for k, v in credit.items() if v is not None}
    return result


def text(credit):
    """'author, source, license' of a credit."""
    return ', '.join(credit[k] for k in TEXT_FIELDS if credit.get(k))


def credit_function(page, credits):
    """The Jinja function credit(file) of a page."""
    def credit(file):
        if file not in credits:
            raise CreditsError(f"{page.label}: no credit for '{file}' (credits of its config.yaml)")
        return text(credits[file])
    return credit


def all_credits(pages, credits_of):
    """Credits of the pages, in order, once each: [{page, title, file, text, ...}]."""
    result, seen = [], set()
    for page in pages:
        for file, credit in credits_of[id(page)].items():
            key = (str(page.src.parent), file)
            if key not in seen:
                seen.add(key)
                result.append({'page': page.site_html, 'title': page.title, 'file': file,
                               'text': text(credit), **credit})
    return result


def files_used(source_text):
    """Relative files of images and videos used by a page source."""
    found = []
    for m in FILE_REFERENCE.finditer(source_text):
        file = m.group(1) or m.group(2)
        if file and '://' not in file and not file.startswith(('/', '{', 'data:')) and MEDIA.search(file) \
                and file not in found:
            found.append(file)
    return found


def _cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def credits_markdown(pages, credits_of, base):
    """structure/credits.md: origin of the pages, credits, images without credit."""
    out = ['# Origin of the slides and credits', '',
           'Written by the generator at each build (lib/credits.py) from the `origin` and `credits`',
           'of the config.yaml of the pages (or of their deck entry).', '',
           '## Slides', '', '| n | page | title | source | origin |', '|---|---|---|---|---|']
    for n, page in enumerate(pages, 1):
        origin = {**page.config, **page.meta}.get('origin') or (f'project {page.source.name}' if page.source.name else '')
        out.append(f'| {n} | {page.site_html} | {_cell(page.title)} | `{os.path.relpath(page.src, base)}` | {_cell(origin)} |')
    credited = all_credits(pages, credits_of)
    out += ['', f'## Credits ({len(credited)})', '', '| page | file | author | source | license |', '|---|---|---|---|---|']
    for c in credited:
        source = f"[{_cell(c.get('source') or c['url'])}]({c['url']})" if c.get('url') else _cell(c.get('source', ''))
        out.append(f"| {c['page']} | `{c['file']}` | {_cell(c.get('author', ''))} | {source} | {_cell(c.get('license', ''))} |")
    missing, seen = [], set()
    for page in pages:
        if str(page.src) in seen:
            continue
        seen.add(str(page.src))
        with open(page.src, encoding='utf-8', errors='replace') as fid:
            used = files_used(fid.read())
        missing += [(page, f) for f in used if f not in credits_of[id(page)]]
    out += ['', f'## Images and videos without credit ({len(missing)})', '',
            'Your own figures need none; the others need a credit in the config.yaml of their page.', '']
    out += [f'- {page.site_html}: `{file}`' for page, file in missing]
    return '\n'.join(out) + '\n', len(credited), len(missing)


def placeholders(pages):
    """Planned figures: [(page, line, text)] of the placeholder:: of the pages."""
    found, seen = [], set()
    for page in pages:
        if str(page.src) in seen:
            continue
        seen.add(str(page.src))
        with open(page.src, encoding='utf-8', errors='replace') as fid:
            for number, line in enumerate(fid, 1):
                found += [(page, number, m.group(1).strip()) for m in PLACEHOLDER.finditer(line)]
    return found


def todo_markdown(planned_figures, planned_slides, base):
    """structure/todo.md: planned figures and slides."""
    out = ['# To do', '', f'## Planned figures ({len(planned_figures)})', '',
           'The `placeholder::` of the pages.', '']
    out += [f'- `{os.path.relpath(page.src, base)}:{line}` ({page.site_html}): {text or "-"}'
            for page, line, text in planned_figures]
    out += ['', f'## Planned slides ({len(planned_slides)})', '',
            'Entries of the deck with a title and no source yet (`--scaffold` creates them).', '']
    out += [f"- `{e.pointer}`: {e.meta.get('title')}" for e in planned_slides]
    return '\n'.join(out) + '\n'
