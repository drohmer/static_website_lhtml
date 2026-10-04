"""Deck: the order of the pages, given by pointers to the sources.

Without a deck, the pages are generated in the order of the files. A deck
(`deck: deck.yaml` in the configuration, or `--deck`) lists pointers instead:

    sources:                              # other projects (paths relative to the deck)
      course: ../course_slides/src        # their pages are generated under course/
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
several pages (`course/intro.html`). A pointer naming a page (its directory
or file) takes precedence over parent directories and globs: `- 02_rotations`
then `- 02_rotations/15_slerp` moves 15_slerp after the rest of the section.
Naming a page again creates another occurrence. Pages of the project that are
not in the deck are not generated (listed in the log).
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
import difflib
import fnmatch
import re
import unicodedata

import yaml

from lib.generator_tool import STRUCTURE_KEYS
from lib.pages import is_template, template_name

GLOB_CHARS = set('*?[')
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]*$')
ALIAS = re.compile(r'([A-Za-z][A-Za-z0-9_-]*):(?!/)(.*)$')
# Directories of the site written by the generator (not available as source names)
GENERATOR_DIRECTORIES = {'theme', 'structure', 'sitemap'}


class DeckError(ValueError):
    """Invalid deck file or pointer (the message starts with 'Deck: ')."""

    def __init__(self, message):
        super().__init__(f'Deck: {message}')


@dataclass
class Entry:
    pointer: str                # path relative to its source directory
    meta: dict = field(default_factory=dict)
    exclude: bool = False
    line: str = ''
    source: str | None = None   # None: the project

    @property
    def is_glob(self):
        return bool(GLOB_CHARS & set(self.pointer))

    @property
    def label(self):
        return f'{self.source}:{self.pointer}' if self.source else self.pointer


@dataclass
class Deck:
    entries: list
    sources: dict = field(default_factory=dict)   # name -> absolute directory (trailing /)


@dataclass
class DeckResult:
    pages: list                 # Page objects in deck order
    unlisted: list              # pages of the project not in the deck
    missing: list               # entries (with a title) whose page does not exist yet
    warnings: list

    def duration(self):
        """(minutes, number of timed pages). The duration of a directory or a
        glob is the duration of all its pages together: it is counted once."""
        durations, timed = {}, 0
        for page in self.pages:
            if 'duration' in page.meta:
                durations[page.deck_line] = page.meta['duration']
                timed += 1
        return sum(durations.values()), timed

    def summary(self):
        text = f'{len(self.pages)} pages'
        external = sum(1 for p in self.pages if p.source.name)
        repeated = sum(1 for p in self.pages if p.occurrence > 1)
        if external:
            text += f', {external} from other projects'
        if repeated:
            text += f', {repeated} repeated'
        minutes, timed = self.duration()
        if timed:
            text += f', {minutes:g} min' + (f' ({timed} pages timed)' if timed < len(self.pages) else '')
        return text


def _normalize(pointer):
    pointer = unicodedata.normalize('NFC', str(pointer).strip().replace('\\', '/'))
    while pointer.startswith('./'):
        pointer = pointer[2:]
    return pointer.strip('/')


def _load_sources(sources, base, origin):
    if sources is None:
        return {}
    if not isinstance(sources, dict):
        raise DeckError(f"{origin}: 'sources' must be a mapping name: path")
    result = {}
    for name, path in sources.items():
        where = f"{origin}, source '{name}'"
        if not isinstance(name, str) or not NAME.match(name):
            raise DeckError(f'{where}: invalid name (letters, digits, - and _)')
        if name.lower() in GENERATOR_DIRECTORIES:
            raise DeckError(f"{where}: '{name}/' is a directory of the generator; choose another name")
        if not isinstance(path, str):
            raise DeckError(f'{where}: expected the path of a source directory')
        root = Path(path).expanduser()
        if not root.is_absolute():
            root = Path(base) / root
        if not root.is_dir():
            raise DeckError(f"{where}: directory not found '{root}'")
        result[name] = str(root.resolve()) + '/'
    return result


def _load_entry(item, sources, where):
    if isinstance(item, str):
        exclude = item.strip().startswith('!')
        raw, meta = (item.strip()[1:] if exclude else item), {}
    elif isinstance(item, dict):
        if not isinstance(item.get('path'), str):
            raise DeckError(f"{where}: a slide given as a mapping needs a 'path'")
        raw, exclude = item['path'], False
        meta = {k: v for k, v in item.items() if k != 'path'}
        bad = (set(meta) & STRUCTURE_KEYS) | {k for k in meta if not isinstance(k, str)}
        if bad:
            raise DeckError(f"{where}: reserved key(s) {', '.join(sorted(map(str, bad)))}")
        duration = meta.get('duration', 0)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
            raise DeckError(f"{where}: 'duration' must be a number of minutes")
        if 'title' in meta and (isinstance(meta['title'], (bool, list, dict)) or not str(meta['title'] or '').strip()):
            raise DeckError(f"{where}: 'title' must be a text")
        params = meta.get('params', {})
        if not isinstance(params, dict) or any(not isinstance(k, str) for k in params):
            raise DeckError(f"{where}: 'params' must be a mapping name: value")
    elif isinstance(item, (int, float)) and not isinstance(item, bool):
        raise DeckError(f"{where}: {item!r} is read as a number: quote the path ('{item}')")
    else:
        raise DeckError(f'{where}: expected a path or a mapping, got {item!r}')
    alias = None
    m = ALIAS.match(str(raw).strip())
    if m and m.group(1) in sources:      # name:path (otherwise a path containing ':')
        alias, raw = m.group(1), m.group(2)
    pointer = _normalize(raw)
    if (not pointer and not alias) or '..' in pointer.split('/'):
        raise DeckError(f'{where}: invalid path {item!r} (relative to the source directory)')
    return Entry(pointer, meta, exclude, where, alias)


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
            raise DeckError(f"cannot read '{origin}': {exc}") from exc
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
    return Deck([_load_entry(item, sources, f'{origin}, slide {k}') for k, item in enumerate(source, 1)],
                sources)


def check_sources(deck, source_directory, site_directory=None):
    """The pages of a source are generated under <name>/: it must not be a
    directory of the project. A source must not contain the site (it would
    read the pages being generated)."""
    for name, root in deck.sources.items():
        if (Path(source_directory) / name).exists():
            raise DeckError(f"source '{name}': the project already has a directory '{name}/' "
                            f"(where its pages would be generated); rename the source")
        if site_directory is not None:
            site = Path(site_directory).resolve()
            if site == Path(root) or Path(root) in site.parents:
                raise DeckError(f"source '{name}': its directory '{root}' contains the site "
                                f"'{site}'; point to the source directory of the project")


def deck_source(cli_value, configured, config_directory):
    """The deck to use: the --deck file (relative to the current directory, else
    to the configuration directory), else the 'deck' of the configuration."""
    if not cli_value:
        return configured
    path = Path(cli_value).expanduser()
    if not path.is_absolute() and not path.exists() and (Path(config_directory) / path).exists():
        path = Path(config_directory) / path
    return str(path.resolve())


def watched_paths(source, config_directory):
    """Files and directories a deck depends on (for --watch): the deck file and,
    in the other projects, the directories its pointers name (the directory of
    a page file; not the whole projects). An invalid deck gives only its file."""
    paths = [Path(source)] if isinstance(source, (str, Path)) else []
    try:
        loaded = load_deck(source, config_directory) if source is not None else None
    except DeckError:
        return paths
    for e in (loaded.entries if loaded else []):
        if e.source:
            fixed = re.split(r'[*?\[]', e.pointer)[0]
            if e.is_glob:
                fixed = fixed.rpartition('/')[0]
            path = Path(loaded.sources[e.source]) / fixed
            paths.append(path if path.is_dir() else path.parent)
    return paths


class _Index:
    """Pages by name (directory, file) and by directory prefix, per source."""

    def __init__(self, pages):
        self.pages = pages
        self.order = {id(p): k for k, p in enumerate(pages)}
        self.by_id = defaultdict(list)
        self.by_file = defaultdict(list)
        self.by_source = defaultdict(list)
        for page in pages:
            source = page.source.name
            self.by_source[source].append(page)
            self.by_id[(source, page.id)].append(page)
            for key in {page.file, template_name(page.file), page.file[:-len('.html')]}:
                self.by_file[(source, key)].append(page)
        self.sorted_ids = {source: sorted((p.id, self.order[id(p)]) for p in ps)
                           for source, ps in self.by_source.items()}

    def _under(self, source, pointer):
        """Order numbers of the pages in subdirectories of `pointer`."""
        ids = self.sorted_ids.get(source, [])
        if not pointer:
            return [k for pid, k in ids if pid]
        return [k for _, k in ids[bisect_left(ids, (pointer + '/', -1)):
                                  bisect_left(ids, (pointer + '0', -1))]]   # '0' follows '/'

    def named(self, entry):
        """Pages named by the pointer itself: their file, or their directory
        when it holds no other page below it (else the pointer is a parent
        directory: all its pages)."""
        if entry.is_glob:
            return []
        key = (entry.source, entry.pointer)
        pages = list(self.by_file.get(key, []))
        if not self._under(entry.source, entry.pointer):
            pages += [p for p in self.by_id.get(key, []) if p not in pages]
        return pages

    def matching(self, entry):
        """Pages named by the pointer, under it (directory), or matching it (glob)."""
        pages = self.by_source.get(entry.source, [])
        p = entry.pointer
        if not p:
            return list(pages)
        if entry.is_glob:
            return [q for q in pages if fnmatch.fnmatchcase(q.id, p) or fnmatch.fnmatchcase(q.file, p)]
        hits = set(self._under(entry.source, p)) | {self.order[id(q)] for q in self.by_id.get((entry.source, p), [])} \
            | {self.order[id(q)] for q in self.by_file.get((entry.source, p), [])}
        return [self.pages[k] for k in sorted(hits)]


def apply_deck(deck, pages):
    """Pages in deck order. `pages`: Page objects of the project then of the
    other sources, in file order. A page named explicitly several times gives
    several occurrences."""
    index = _Index(pages)
    warnings = []
    excluded = set()
    for e in (e for e in deck.entries if e.exclude):
        hits = index.matching(e)
        if not hits:
            warnings.append(f"{e.line}: '!{e.label}' excludes no page")
        excluded.update(id(p) for p in hits)

    includes = [e for e in deck.entries if not e.exclude]
    explicit = {}
    for e in includes:
        named = index.named(e)
        explicit[id(e)] = named[0] if len(named) == 1 else None
    named_pages = {id(p) for p in explicit.values() if p is not None}

    ordered, placed, missing, occurrences = [], set(), [], {}
    for e in includes:
        meta = {k: v for k, v in e.meta.items() if k != 'params'}
        params = e.meta.get('params', {})
        page = explicit[id(e)]
        if page is not None:
            if id(page) in excluded:
                warnings.append(f"{e.line}: '{e.label}' is listed but also excluded (not generated)")
                continue
            placed.add(id(page))
            n = occurrences[id(page)] = occurrences.get(id(page), 0) + 1
            if n == 1:
                page.meta, page.params, page.deck_line = meta, params, e.line
            else:
                page = replace(page, meta=meta, params=params, deck_line=e.line, occurrence=n)
            ordered.append(page)
            continue
        hits = index.matching(e)
        if not hits:
            if 'title' in e.meta and not e.is_glob and not e.source:
                missing.append(e)
                continue
            hint = difflib.get_close_matches(e.label, sorted({p.label for p in pages}), n=1)
            alias = ALIAS.match(e.pointer)
            raise DeckError(f"{e.line}: no page matches '{e.label}'"
                            + (f" (did you mean '{hint[0]}'?)" if hint else '')
                            + (f" (no source named '{alias.group(1)}')" if alias and not e.source else ''))
        # Pages named explicitly in the deck are placed there, not here.
        if all(id(p) in placed or id(p) in excluded or id(p) in named_pages for p in hits):
            first = hits[0]
            name = (f'{first.source.name}:' if first.source.name else '') + first.file
            warnings.append(f"{e.line}: '{e.label}' places no page (its pages are placed elsewhere); "
                            f"to repeat a page, name its file ('{name}')")
        for page in hits:
            if id(page) in placed or id(page) in excluded or id(page) in named_pages:
                continue
            placed.add(id(page))
            page.meta, page.params, page.deck_line = dict(meta), params, e.line
            ordered.append(page)
    unlisted = [p for p in pages if id(p) not in placed and not p.source.name]
    return DeckResult(ordered, unlisted, missing, warnings)


def named_pages(pages, pointers, sources=None):
    """The pages (among `pages`, with their occurrences) named by pointers
    written as in a deck (--only). `sources`: names of the other projects."""
    index = _Index(pages)
    found = set()
    for k, pointer in enumerate(pointers, 1):
        entry = _load_entry(pointer, sources or {}, f'--only {pointer}')
        hits = index.matching(entry)
        if not hits:
            hint = difflib.get_close_matches(entry.label, sorted({p.label for p in pages}), n=1)
            raise DeckError(f"--only: no page of the site matches '{entry.label}'"
                            + (f" (did you mean '{hint[0]}'?)" if hint else ''))
        found.update(id(p) for p in hits)
    return [p for p in pages if id(p) in found]


def scaffold(entries, source_directory):
    """Create the source of planned slides (DeckResult.missing: entries with a
    title that match no page): <source>/<path>/index.html.j2 with the title and
    the other metadata as LHTML comments. A directory holding pages, at any
    depth, is never modified. Returns the paths."""
    created = []
    for e in entries:
        if e.source:
            continue
        target = Path(source_directory) / e.pointer
        if target.name.endswith('.html') or is_template(target.name):     # a page file: dir/extra.html
            page = target if is_template(target.name) else target.with_name(template_name(target.name))
            if page.exists():
                continue
        else:
            page = target / template_name('index.html')
            if page.exists() or any(is_template(p.name) for p in target.rglob('*')):
                continue
        page.parent.mkdir(parents=True, exist_ok=True)
        title = str(e.meta['title']).strip().splitlines() or ['']
        lines = [f"= {_raw(title[0])}", '']
        for key, value in e.meta.items():
            if key != 'title':
                lines += [f'::# {_raw(line)}' for line in f'{key}: {value}'.splitlines()]
        page.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
        created.append(str(page))
    return created


def _raw(text):
    """Text kept as is by Jinja (a title may contain {{ or {%)."""
    text = str(text)
    return f'{{% raw %}}{text}{{% endraw %}}' if ('{{' in text or '{%' in text or '{#' in text) else text
