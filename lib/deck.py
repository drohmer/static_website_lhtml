"""Deck: the order of the pages, given by pointers to the sources.

Without a deck, the pages are generated in the order of the files. A deck
(`deck: deck.yaml` in the configuration, or `--deck`) lists pointers instead:

    sources:                              # other projects (paths relative to the deck)
      course: ../course_slides/src        # pages copied in the site under course/
      lab: {path: ../lab/src, mount: extra/lab}
    slides:
      - 00_ouverture                      # directory: all its pages, in file order
      - 02_rotations/04_representations   # one page
      - 02_rotations/1*                   # glob on the page paths
      - course:05_pipeline/04_depth       # page of another project
      - path: 03_squelette/04_ik          # page with metadata
        title: IK                         # title in the menu
        duration: 2                       # minutes (summed in the build log)
        notes: Show the demo first        # any other key is exported in structure.yaml
      - path: 00_ouverture/01_plan        # the same page again: a new occurrence
        params: {current: 2}              # Jinja variables of this occurrence
      - '!06_recherche/*_todo*'           # excluded, wherever it is listed

A page is identified by its directory relative to its source directory
(`02_rotations/04_representations`), or by its file when a directory holds
several pages (`course/intro.html`). An explicit pointer (naming exactly one
page) takes precedence over directories and globs: `- 02_rotations` then
`- 02_rotations/15_slerp` moves 15_slerp after the rest of the section.
Naming a page explicitly again creates another occurrence of it, generated
next to the first one (index-2.html, ...). Pages that are not in the deck
are not generated (listed in the log).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import difflib
import fnmatch
import os
import re
import shutil

import yaml

from lib.filesystem import FilepathRelative, find_files_in_hierarchy

GLOB_CHARS = set('*?[')
RESERVED = {'path', 'dir', 'filename', 'level'}
ALIAS = re.compile(r'([A-Za-z][A-Za-z0-9_-]*):(?!/)(.*)$')


class DeckError(ValueError):
    """Invalid deck file or pointer."""


@dataclass
class Source:
    name: str
    root: str                   # absolute directory, with trailing /
    mount: str                  # directory of its pages in the site, with trailing /


@dataclass
class Entry:
    pointer: str                # path relative to its source directory
    meta: dict = field(default_factory=dict)
    exclude: bool = False
    line: str = ''
    source: str | None = None   # None: the source directory of the project

    @property
    def is_glob(self):
        return bool(GLOB_CHARS & set(self.pointer))

    @property
    def label(self):
        return f'{self.source}:{self.pointer}' if self.source else self.pointer


@dataclass
class Deck:
    entries: list
    sources: dict = field(default_factory=dict)   # name -> Source


@dataclass
class DeckResult:
    pages: list                 # template entries in deck order (with 'deck' metadata)
    unlisted: list              # local template entries not in the deck
    missing: list               # entries (with a title) whose page does not exist yet
    warnings: list


def _normalize(pointer):
    pointer = str(pointer).strip().replace('\\', '/')
    while pointer.startswith('./'):
        pointer = pointer[2:]
    return pointer.strip('/')


def _relative_directory(value, where):
    value = _normalize(value)
    if not value or '..' in value.split('/'):
        raise DeckError(f'{where}: invalid directory {value!r} (relative, without ..)')
    return value + '/'


def _load_sources(sources, base, origin):
    if sources is None:
        return {}
    if not isinstance(sources, dict):
        raise DeckError(f"{origin}: 'sources' must be a mapping name: path")
    result = {}
    for name, spec in sources.items():
        where = f"{origin}, source '{name}'"
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', name):
            raise DeckError(f'{where}: invalid name (letters, digits, - and _)')
        if isinstance(spec, str):
            spec = {'path': spec}
        if not isinstance(spec, dict) or not isinstance(spec.get('path'), str) \
                or set(spec) - {'path', 'mount'}:
            raise DeckError(f"{where}: expected a path, or a mapping with 'path' and 'mount'")
        root = Path(spec['path']).expanduser()
        if not root.is_absolute():
            root = Path(base) / root
        if not root.is_dir():
            raise DeckError(f"{where}: directory not found '{root}'")
        mount = _relative_directory(spec.get('mount', name), where)
        result[name] = Source(name, str(root.resolve()) + '/', mount)
    return result


def load_deck(source, base_directory='.'):
    """Deck given as a YAML file path, a mapping {'sources': ..., 'slides': [...]}
    or a list of slides. Relative source paths are resolved from the deck file's
    directory (from `base_directory` for a deck given as data)."""
    origin = 'deck'
    if isinstance(source, (str, Path)):
        origin = str(source)
        base_directory = Path(source).resolve().parent
        try:
            with open(source, encoding='utf-8') as stream:
                source = yaml.safe_load(stream)
        except (OSError, yaml.YAMLError) as exc:
            raise DeckError(f"Cannot read deck '{origin}': {exc}") from exc
    sources = {}
    if isinstance(source, dict):
        unknown = set(source) - {'slides', 'title', 'sources'}
        if unknown:
            raise DeckError(f"{origin}: unknown key(s) {', '.join(sorted(unknown))} "
                            f"(expected title, sources, slides)")
        sources = _load_sources(source.get('sources'), base_directory, origin)
        source = source.get('slides')
    if not isinstance(source, list):
        raise DeckError(f"{origin}: expected a list of slides (key 'slides')")
    entries = []
    for k, item in enumerate(source, 1):
        where = f'{origin}, slide {k}'
        if isinstance(item, str):
            exclude = item.strip().startswith('!')
            raw = item.strip()[1:] if exclude else item
            meta = {}
        elif isinstance(item, dict):
            if not isinstance(item.get('path'), str):
                raise DeckError(f"{where}: a slide given as a mapping needs a 'path'")
            raw, exclude = item['path'], False
            meta = {k2: v for k2, v in item.items() if k2 != 'path'}
            bad = (set(meta) & RESERVED) | {k2 for k2 in meta if not isinstance(k2, str)}
            if bad:
                raise DeckError(f"{where}: reserved key(s) {', '.join(sorted(map(str, bad)))}")
            if 'duration' in meta and (isinstance(meta['duration'], bool)
                                       or not isinstance(meta['duration'], (int, float))
                                       or meta['duration'] < 0):
                raise DeckError(f"{where}: 'duration' must be a number of minutes")
            if 'params' in meta and (not isinstance(meta['params'], dict)
                                     or any(not isinstance(k2, str) for k2 in meta['params'])):
                raise DeckError(f"{where}: 'params' must be a mapping name: value")
        else:
            raise DeckError(f'{where}: expected a path or a mapping, got {item!r}')
        alias = None
        m = ALIAS.match(str(raw).strip())
        if m:
            alias, raw = m.group(1), m.group(2)
            if alias not in sources:
                known = ', '.join(sorted(sources)) or 'none'
                raise DeckError(f"{where}: unknown source '{alias}' (sources: {known})")
        pointer = _normalize(raw)
        if (not pointer and not alias) or '..' in pointer.split('/'):
            raise DeckError(f'{where}: invalid path {item!r} (relative to the source directory)')
        entries.append(Entry(pointer, meta, exclude, where, alias))
    return Deck(entries, sources)


def page_id(entry):
    """Directory of the page relative to its source directory, without trailing slash."""
    return entry['path'].path_local.strip('/')


def page_file(entry):
    """File of the page relative to its source directory, as generated (.html)."""
    return (entry['path'].path_local + entry['path'].filename).replace('.html.j2', '.html').strip('/')


def page_label(entry):
    name = page_id(entry) or page_file(entry)
    return f"{entry['source']}:{name}" if entry.get('source') else name


def source_pages(deck):
    """Template entries of the external sources used by the deck, in file order."""
    used = {e.source for e in deck.entries if e.source}
    pages = []
    for name in sorted(used):
        for page in find_files_in_hierarchy(deck.sources[name].root, lambda f: f.endswith('.html.j2')):
            page['source'] = name
            pages.append(page)
    return pages


def _matches(entry, page):
    """The pointer names the page, its directory, a parent directory, or matches as a glob."""
    if entry.source != page.get('source'):
        return False
    pid, pfile = page_id(page), page_file(page)
    p = entry.pointer
    if not p:
        return True
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


def apply_deck(deck, pages):
    """Order and filter the template entries `pages` (local pages in file order,
    then the pages of the external sources) by the deck. A page named
    explicitly several times gives several occurrences (copies of the entry,
    'occurrence' 2, 3, ...)."""
    if isinstance(deck, list):
        deck = Deck(deck)
    warnings = []
    excluded = set()
    for e in (e for e in deck.entries if e.exclude):
        hits = [id(p) for p in pages if _matches(e, p)]
        if not hits:
            warnings.append(f"{e.line}: '!{e.label}' excludes no page")
        excluded.update(hits)

    includes = [e for e in deck.entries if not e.exclude]
    explicit = {id(e): _explicit_page(e, pages) for e in includes}
    named = {id(page) for page in explicit.values() if page is not None}

    ordered, placed, missing, occurrences = [], set(), [], {}
    for e in includes:
        page = explicit[id(e)]
        if page is not None:
            if id(page) in excluded:
                warnings.append(f"{e.line}: '{e.label}' is listed but also excluded (not generated)")
                continue
            occurrences[id(page)] = occurrences.get(id(page), 0) + 1
            n = occurrences[id(page)]
            item = page if n == 1 else {**page, 'occurrence': n}
            item['deck'] = dict(e.meta)
            placed.add(id(page))
            ordered.append(item)
            continue
        all_hits = [p for p in pages if _matches(e, p)]
        if not all_hits:
            if 'title' in e.meta and not e.is_glob and not e.source:
                missing.append(e)
                continue
            known = sorted({page_label(p) for p in pages} | {page_file(p) for p in pages
                                                              if not p.get('source')})
            hint = difflib.get_close_matches(e.label, known, n=1)
            raise DeckError(f"{e.line}: no page matches '{e.label}'"
                            + (f" (did you mean '{hint[0]}'?)" if hint else ''))
        # Pages named explicitly in the deck are placed there, not here.
        for page in all_hits:
            if id(page) in placed or id(page) in excluded or id(page) in named:
                continue
            placed.add(id(page))
            page['deck'] = dict(e.meta)
            ordered.append(page)
    unlisted = [p for p in pages if id(p) not in placed and not p.get('source')]
    return DeckResult(ordered, unlisted, missing, warnings)


def _copy_assets(source_dir, target_dir):
    """Copy the files of a page directory and its subdirectories without pages
    (assets), not the pages themselves (.html.j2)."""
    os.makedirs(target_dir, exist_ok=True)
    for name in sorted(os.listdir(source_dir)):
        if name in ('.git', '.DS_Store') or name.endswith('.html.j2'):
            continue
        path = os.path.join(source_dir, name)
        target = os.path.join(target_dir, name)
        if os.path.isdir(path) and not os.path.islink(path):
            has_pages = any(f.endswith('.html.j2') for _, _, files in os.walk(path) for f in files)
            if not has_pages:
                shutil.copytree(path, target, symlinks=True, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns('.git', '.DS_Store'))
        elif not os.path.lexists(target):
            shutil.copy2(path, target, follow_symlinks=False)


def _occurrence_name(filename, n, taken):
    stem = filename[:-len('.html.j2')]
    k = n
    while f'{stem}-{k}.html.j2' in taken:
        k += 1
    return f'{stem}-{k}.html.j2'


def materialize(pages, site_directory, sources, copy_assets=True):
    """Place the pages of the deck in the site directory and return their
    template entries there: pages of other projects (under their mount
    directory, with their assets when `copy_assets`), pages read from the
    source directory (light mode), and occurrences (copies next to the page)."""
    site = os.path.join(site_directory, '')
    result, copied_dirs = [], set()
    taken = {}   # site directory -> file names used
    for page in pages:
        path = page['path']
        mount = sources[page['source']].mount if page.get('source') else ''
        local_dir = mount + path.path_local
        target_dir = os.path.join(site, local_dir)
        source_file = path.filepath()
        if page.get('source') and copy_assets and target_dir not in copied_dirs:
            _copy_assets(os.path.dirname(source_file), target_dir)
            copied_dirs.add(target_dir)
        names = taken.setdefault(target_dir, set(
            f for f in (os.listdir(target_dir) if os.path.isdir(target_dir) else [])))
        filename = path.filename
        if page.get('occurrence', 1) > 1:
            filename = _occurrence_name(filename, page['occurrence'], names)
        names.add(filename)
        target_file = os.path.join(target_dir, filename)
        if os.path.abspath(source_file) != os.path.abspath(target_file):
            os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(source_file, target_file)
        entry = {**page, 'path': FilepathRelative(root_directory=site, path_local=local_dir,
                                                  filename=filename, level=local_dir.count('/'))}
        result.append(entry)
    return result


def check_mounts(deck, source_directory):
    """A mount directory must not hide a directory of the project sources."""
    for source in deck.sources.values():
        if (Path(source_directory) / source.mount).exists():
            raise DeckError(f"source '{source.name}': mount directory '{source.mount}' already exists "
                            f"in the sources; choose another 'mount'")


def scaffold(entries, source_directory):
    """Create the source of the deck slides that do not exist yet (entries with a
    title): <source>/<path>/index.html.j2 with the title and the other metadata
    as an LHTML comment. Existing files are never overwritten. Returns the paths."""
    created = []
    for e in entries:
        if e.source:
            continue
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
