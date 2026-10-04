"""Pages: the templates of a site, where they come from and where they are generated.

A Source is a directory of templates: the project (`name` None) or another
project named in the deck (its pages are generated under `<name>/`). A Page
is one template of a source; a page listed several times in a deck gives
several Page objects (occurrences). Every page goes through the same steps:
discover (sources) -> select (deck) -> name_outputs -> place (site); then
the generator renders them (Jinja, LHTML) and exports them (structure.yaml).
The names of templates are given by is_template, html_name and template_name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
import os
import shutil
import unicodedata

import yaml

from lib.filesystem import ignore_hidden, copy_tree, find_files_in_hierarchy
from lib import source_scan
from lib.generator_tool import STRUCTURE_KEYS

TEMPLATE_SUFFIX = '.j2'         # the template of a page index.html is index.html.j2


def is_template(name):
    """Whether a file is the template of a page (index.html.j2)."""
    return name.endswith('.html' + TEMPLATE_SUFFIX)


def html_name(name):
    """index.html.j2 -> index.html (other names unchanged)"""
    return name[:-len(TEMPLATE_SUFFIX)] if is_template(name) else name


def template_name(name):
    """index.html -> index.html.j2"""
    return name + TEMPLATE_SUFFIX


@dataclass(frozen=True)
class Source:
    name: str | None            # None: the project itself
    root: str                   # absolute directory, with trailing /

    @property
    def prefix(self):
        """Directory of its pages in the site."""
        return '' if self.name is None else self.name + '/'


@dataclass(eq=False)
class Page:
    source: Source
    directory: str              # relative to the source root: '' or 'a/b/'
    template: str               # file name in the source: index.html.j2
    config: dict = field(default_factory=dict)    # config.yaml of its directory
    meta: dict = field(default_factory=dict)      # deck metadata (title, duration, notes, ...)
    params: dict = field(default_factory=dict)    # Jinja variables of this occurrence
    occurrence: int = 1
    deck_line: str = ''         # deck entry that placed the page
    position: int = 0           # order of the page in its source (files)
    name: str = ''              # template name in the site (set by name_outputs)
    title: str = ''             # set by generator_tool.extract_titles

    @property
    def id(self):
        """Directory relative to the source, without trailing slash (Unicode NFC,
        as typed in a deck, whatever the file system stores)."""
        return unicodedata.normalize('NFC', self.directory.strip('/'))

    @property
    def file(self):
        """File relative to the source, as generated (a/index.html), NFC."""
        return unicodedata.normalize('NFC', (self.directory + html_name(self.template)).strip('/'))

    @property
    def label(self):
        name = (self.id if html_name(self.template) == 'index.html' else self.file) or self.file
        return f'{self.source.name}:{name}' if self.source.name else name

    @property
    def src(self):
        return Path(self.source.root) / self.directory / self.template

    @cached_property
    def text(self):
        """Its source, read once by the scanners (titles, lint, credits...)."""
        try:
            with open(self.src, encoding='utf-8') as fid:
                return fid.read()
        except UnicodeDecodeError as exc:
            raise ValueError(f"'{self.src}' is not UTF-8 text (byte {exc.start}): "
                             f"save it in UTF-8") from None

    @cached_property
    def scan(self):
        """Its zones and its text read as LHTML (lib/source_scan.py), computed once."""
        return source_scan.Scan(self.text)

    @property
    def settings(self):
        """Its settings: its config.yaml, then its deck entry (which takes precedence)."""
        return {**self.config, **self.meta}

    @property
    def site_directory(self):
        return self.source.prefix + self.directory

    @property
    def site_template(self):
        """Template in the site, relative to the site: a/index-2.html.j2"""
        return self.site_directory + (self.name or self.template)

    @property
    def site_html(self):
        """Generated page, relative to the site: a/index-2.html"""
        return html_name(self.site_template)

    @property
    def path_to_root(self):
        return '../' * self.site_directory.count('/')


def _read_config(directory, cache):
    if directory not in cache:
        path = os.path.join(directory, 'config.yaml')
        config = {}
        if os.path.isfile(path):
            with open(path) as fid:
                config = yaml.safe_load(fid)
            if config is None:
                config = {}
            if not isinstance(config, dict) or any(not isinstance(key, str) for key in config):
                raise ValueError(f"Invalid page configuration '{path}': expected key: value pairs")
            reserved = sorted(set(config) & STRUCTURE_KEYS)
            if reserved:
                raise ValueError(f"Invalid page configuration '{path}': reserved key(s) "
                                 f"{', '.join(reserved)} (written by the generator in structure.yaml)")
        cache[directory] = config
    return cache[directory]


def discover(source, exclude=()):
    """Pages of a source, in file order, with the config.yaml of their
    directory. Hidden files and directories at the top level of the source
    are ignored (as they are not copied into the site), and the directories
    `exclude` (the site)."""
    cache = {}
    found = [f['path'] for f in find_files_in_hierarchy(source.root, is_template, exclude=exclude)]
    found = [f for f in found if not (f.path_local or f.filename).startswith('.')]
    return [Page(source, f.path_local, f.filename, position=k,
                 config=_read_config(source.root + f.path_local, cache))
            for k, f in enumerate(found)]


def name_outputs(pages):
    """Template name of each page in the site: its own name, and for the
    occurrences index-2.html.j2, index-3.html.j2, ... skipping the templates
    and pages of its source directory, so that the names are the same in
    every build."""
    taken = {}
    for page in pages:
        if page.occurrence == 1:
            page.name = page.template
            continue
        names = taken.get(page.site_directory)
        if names is None:
            names = taken[page.site_directory] = {html_name(f) for f in os.listdir(page.src.parent)}
        stem = html_name(page.template)[:-len('.html')]
        k = page.occurrence
        while f'{stem}-{k}.html' in names:
            k += 1
        names.add(f'{stem}-{k}.html')
        page.name = template_name(f'{stem}-{k}.html')


def copy_assets(source_dir, target_dir):
    """Copy the assets of a page directory: its files and its subdirectories
    without templates (those of other pages), not the templates (see
    filesystem.copy_tree). Returns the warnings."""
    hidden = ignore_hidden(source_dir, skip=is_template)
    top = os.path.abspath(source_dir)

    def ignore(directory, names):
        skipped = hidden(directory, names)
        if os.path.abspath(directory) == top:
            skipped |= {n for n in names if os.path.isdir(os.path.join(directory, n))
                        and any(is_template(f) for _, _, files in os.walk(os.path.join(directory, n))
                                for f in files)}
        return skipped
    return copy_tree(source_dir, target_dir, ignore)


def place(pages, site_directory, project_assets=False, transform=None):
    """Copy the templates of the pages into the site, with the assets of their
    directory for the pages of other projects (those of the project are copied
    with its whole directory), and of the project too with `project_assets`
    (--only: the sources are not copied). `transform(text)`: applied to the
    templates (source map). Returns the warnings."""
    site = os.path.join(site_directory, '')
    real_site = os.path.join(os.path.realpath(site), '')
    copied, warnings = set(), []
    for page in pages:
        target_dir = site + page.site_directory
        if not os.path.join(os.path.realpath(target_dir), '').startswith(real_site):
            raise ValueError(f"'{target_dir}' leads out of the site directory (symbolic link?): "
                             f"refusing to write {page.label} there")
        os.makedirs(target_dir, exist_ok=True)
        if (page.source.name or project_assets) and page.site_directory not in copied:
            warnings += copy_assets(str(page.src.parent), target_dir)
            copied.add(page.site_directory)
        if transform is None:
            shutil.copy2(page.src, site + page.site_template)
        else:
            with open(site + page.site_template, 'w', encoding='utf-8') as fid:
                fid.write(transform(page.text))
    return warnings
