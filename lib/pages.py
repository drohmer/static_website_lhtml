"""Pages: the templates of a site, where they come from and where they are generated.

A Source is a directory of templates: the project (`name` None) or another
project named in the deck (its pages are generated under `<name>/`). A Page
is one template of a source; a page listed several times in a deck gives
several Page objects (occurrences). Every page goes through the same steps:
discover (sources) -> select (deck) -> name_outputs -> place (site).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import shutil

import yaml

from lib.filesystem import FilepathRelative, find_files_in_hierarchy

TEMPLATE_SUFFIX = '.html.j2'


def html_name(template_name):
    """index.html.j2 -> index.html"""
    return template_name[:-len('.j2')] if template_name.endswith('.j2') else template_name


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
    name: str = ''              # template name in the site (set by name_outputs)

    @property
    def id(self):
        """Directory relative to the source, without trailing slash."""
        return self.directory.strip('/')

    @property
    def file(self):
        """File relative to the source, as generated (a/index.html)."""
        return (self.directory + html_name(self.template)).strip('/')

    @property
    def label(self):
        name = (self.id if self.template == 'index' + TEMPLATE_SUFFIX else self.file) or self.file
        return f'{self.source.name}:{name}' if self.source.name else name

    @property
    def src(self):
        return Path(self.source.root) / self.directory / self.template

    @property
    def site_directory(self):
        return self.source.prefix + self.directory

    def entry(self, site_directory):
        """Template entry of the generator (path in the site, metadata for structure.yaml)."""
        return {'path': FilepathRelative(root_directory=site_directory, path_local=self.site_directory,
                                         filename=self.name or self.template,
                                         level=self.site_directory.count('/')),
                'page': self,
                'extra-config': {**self.config, **self.meta}}


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
        cache[directory] = config
    return cache[directory]


def discover(source):
    """Pages of a source, in file order, with the config.yaml of their directory."""
    cache = {}
    return [Page(source, f['path'].path_local, f['path'].filename,
                 config=_read_config(source.root + f['path'].path_local, cache))
            for f in find_files_in_hierarchy(source.root, lambda name: name.endswith(TEMPLATE_SUFFIX))]


def name_outputs(pages):
    """Template name of each page in the site: its own name, and for the
    occurrences index-2.html.j2, index-3.html.j2, ... skipping the templates
    of its source directory, so that the names are the same in every build."""
    taken = {}
    for page in pages:
        if page.occurrence == 1:
            page.name = page.template
            continue
        names = taken.get(page.site_directory)
        if names is None:
            names = taken[page.site_directory] = {
                f for f in os.listdir(page.src.parent) if f.endswith(TEMPLATE_SUFFIX)}
        stem = page.template[:-len(TEMPLATE_SUFFIX)]
        k = page.occurrence
        while f'{stem}-{k}{TEMPLATE_SUFFIX}' in names:
            k += 1
        page.name = f'{stem}-{k}{TEMPLATE_SUFFIX}'
        names.add(page.name)


def copy_assets(source_dir, target_dir):
    """Copy the files of a page directory and its subdirectories without
    templates (assets), not the templates."""
    os.makedirs(target_dir, exist_ok=True)
    for name in sorted(os.listdir(source_dir)):
        if name in ('.git', '.DS_Store') or name.endswith(TEMPLATE_SUFFIX):
            continue
        path = os.path.join(source_dir, name)
        target = os.path.join(target_dir, name)
        if os.path.isdir(path) and not os.path.islink(path):
            if not any(f.endswith(TEMPLATE_SUFFIX) for _, _, files in os.walk(path) for f in files):
                shutil.copytree(path, target, symlinks=True, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns('.git', '.DS_Store'))
        elif not os.path.lexists(target):
            shutil.copy2(path, target, follow_symlinks=False)


def place(pages, site_directory, light=False):
    """Copy the templates of the pages into the site, with the assets of the
    pages of other projects (light mode: only for directories not in the site
    yet; the assets of the project are copied with its whole directory).
    Returns the template entries."""
    site = os.path.join(site_directory, '')
    copied = set()
    for page in pages:
        target_dir = site + page.site_directory
        if page.source.name and target_dir not in copied:
            if not (light and os.path.isdir(target_dir)):
                copy_assets(str(page.src.parent), target_dir)
            copied.add(target_dir)
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(page.src, target_dir + page.name)
    return [page.entry(site) for page in pages]
