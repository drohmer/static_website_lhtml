"""Deck: the order of the pages, given by pointers to the sources.

Without a deck, the pages are generated in the order of the files. A deck
(`deck: deck.yaml` in the configuration, or `--deck`) lists pointers instead:

    slides:
      - 00_ouverture                      # directory: all its pages, in file order
      - 02_rotations/04_representations   # one page
      - 02_rotations/1*                   # glob on the page paths
      - path: 03_squelette/04_ik          # page with metadata
        title: IK                         # title in the menu
        duration: 2                       # minutes (summed in the build log)
        notes: Show the demo first        # any other key is exported in structure.yaml
      - '!06_recherche/*_todo*'           # excluded, wherever it is listed

A page is identified by its directory relative to the source directory
(`02_rotations/04_representations`), or by its file when a directory holds
several pages (`course/intro.html`). An explicit pointer to a page takes
precedence over directories and globs: `- 02_rotations` then
`- 02_rotations/15_slerp` moves 15_slerp after the rest of the section.
Pages that are not in the deck are not generated (listed in the log).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import difflib
import fnmatch

import yaml

GLOB_CHARS = set('*?[')
RESERVED = {'path', 'dir', 'filename', 'level'}


class DeckError(ValueError):
    """Invalid deck file or pointer."""


@dataclass
class Entry:
    pointer: str
    meta: dict = field(default_factory=dict)
    exclude: bool = False
    line: str = ''

    @property
    def is_glob(self):
        return bool(GLOB_CHARS & set(self.pointer))


@dataclass
class DeckResult:
    pages: list                 # template entries in deck order (with 'deck' metadata)
    unlisted: list              # template entries not in the deck
    missing: list               # entries (with a title) whose page does not exist yet
    warnings: list


def _normalize(pointer):
    pointer = str(pointer).strip().replace('\\', '/')
    while pointer.startswith('./'):
        pointer = pointer[2:]
    return pointer.strip('/')


def load_deck(source):
    """Entries of a deck given as a YAML file path, a mapping {'slides': [...]} or a list."""
    origin = 'deck'
    if isinstance(source, (str, Path)):
        origin = str(source)
        try:
            with open(source, encoding='utf-8') as stream:
                source = yaml.safe_load(stream)
        except (OSError, yaml.YAMLError) as exc:
            raise DeckError(f"Cannot read deck '{origin}': {exc}") from exc
    if isinstance(source, dict):
        unknown = set(source) - {'slides', 'title'}
        if unknown:
            raise DeckError(f"{origin}: unknown key(s) {', '.join(sorted(unknown))} (expected slides, title)")
        source = source.get('slides')
    if not isinstance(source, list):
        raise DeckError(f"{origin}: expected a list of slides (key 'slides')")
    entries = []
    for k, item in enumerate(source, 1):
        where = f'{origin}, slide {k}'
        if isinstance(item, str):
            exclude = item.strip().startswith('!')
            pointer = _normalize(item.strip()[1:] if exclude else item)
            meta = {}
        elif isinstance(item, dict):
            if not isinstance(item.get('path'), str):
                raise DeckError(f"{where}: a slide given as a mapping needs a 'path'")
            pointer, exclude = _normalize(item['path']), False
            meta = {k2: v for k2, v in item.items() if k2 != 'path'}
            bad = (set(meta) & RESERVED) | {k2 for k2 in meta if not isinstance(k2, str)}
            if bad:
                raise DeckError(f"{where}: reserved key(s) {', '.join(sorted(map(str, bad)))}")
            if 'duration' in meta and (isinstance(meta['duration'], bool)
                                       or not isinstance(meta['duration'], (int, float))
                                       or meta['duration'] < 0):
                raise DeckError(f"{where}: 'duration' must be a number of minutes")
        else:
            raise DeckError(f'{where}: expected a path or a mapping, got {item!r}')
        if not pointer or '..' in pointer.split('/'):
            raise DeckError(f'{where}: invalid path {item!r} (relative to the source directory)')
        entries.append(Entry(pointer, meta, exclude, where))
    return entries


def page_id(entry):
    """Directory of the page relative to the sources, without trailing slash."""
    return entry['path'].path_local.strip('/')


def page_file(entry):
    """File of the page relative to the sources, as generated (.html)."""
    return (entry['path'].path_local + entry['path'].filename).replace('.html.j2', '.html').strip('/')


def _matches(entry, page):
    """The pointer names the page, its directory, a parent directory, or matches as a glob."""
    pid, pfile = page_id(page), page_file(page)
    p = entry.pointer
    if entry.is_glob:
        return fnmatch.fnmatchcase(pid, p) or fnmatch.fnmatchcase(pfile, p)
    if p in (pid, pfile, pfile + '.j2') or (pfile.endswith('.html') and p == pfile[:-len('.html')]):
        return True
    return pid.startswith(p + '/')


def _explicit_page(entry, pages):
    """The page named by a pointer that matches exactly one page (not a glob), else None."""
    if entry.exclude or entry.is_glob:
        return None
    hits = [p for p in pages if _matches(entry, p)]
    return hits[0] if len(hits) == 1 else None


def apply_deck(entries, pages):
    """Order and filter the template entries `pages` (in file order) by the deck."""
    warnings = []
    excludes = [e for e in entries if e.exclude]
    excluded = set()
    for e in excludes:
        hits = [id(p) for p in pages if _matches(e, p)]
        if not hits:
            warnings.append(f"{e.line}: '!{e.pointer}' excludes no page")
        excluded.update(hits)

    includes = [e for e in entries if not e.exclude]
    explicit = {id(e): _explicit_page(e, pages) for e in includes}
    first_pointer = {}
    for e in includes:
        if explicit[id(e)] is not None:
            first_pointer.setdefault(id(explicit[id(e)]), e)

    ordered, placed, missing = [], set(), []
    for e in includes:
        page = explicit[id(e)]
        if page is not None:
            if first_pointer[id(page)] is not e:
                warnings.append(f"{e.line}: '{e.pointer}' is already listed "
                                f"({first_pointer[id(page)].line}); kept at its first place")
                continue
            if id(page) in excluded:
                warnings.append(f"{e.line}: '{e.pointer}' is listed but also excluded (not generated)")
            hits = [page]
        else:
            all_hits = [p for p in pages if _matches(e, p)]
            if not all_hits:
                if 'title' in e.meta and not e.is_glob:
                    missing.append(e)
                    continue
                known = sorted({page_id(p) for p in pages} | {page_file(p) for p in pages})
                hint = difflib.get_close_matches(e.pointer, known, n=1)
                raise DeckError(f"{e.line}: no page matches '{e.pointer}'"
                                + (f" (did you mean '{hint[0]}'?)" if hint else ''))
            # Pages named explicitly elsewhere in the deck are placed there.
            hits = [p for p in all_hits if id(p) not in first_pointer]
        for page in hits:
            if id(page) in placed or id(page) in excluded:
                continue
            placed.add(id(page))
            if e.meta:
                page['deck'] = dict(e.meta)
            ordered.append(page)
    unlisted = [p for p in pages if id(p) not in placed]
    return DeckResult(ordered, unlisted, missing, warnings)


def scaffold(entries, source_directory):
    """Create the source of the deck slides that do not exist yet (entries with a
    title): <source>/<path>/index.html.j2 with the title and the other metadata
    as an LHTML comment. Existing files are never overwritten. Returns the paths."""
    created = []
    for e in entries:
        target = Path(source_directory) / e.pointer
        if target.suffix in ('.html', '.j2'):
            continue
        page = target / 'index.html.j2'
        if page.exists() or any(target.glob('*.html.j2')):
            continue
        page.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"= {e.meta['title']}", '']
        for key, value in e.meta.items():
            if key != 'title':
                lines.append(f'::# {key}: {value}')
        page.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
        created.append(str(page))
    return created


def total_duration(pages):
    values = [p['deck']['duration'] for p in pages if 'duration' in p.get('deck', {})]
    return sum(values), len(values)
