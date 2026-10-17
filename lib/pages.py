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

from lib.filesystem import ignore_hidden, copy_tree, find_files_in_hierarchy, read_text, read_yaml
from lib import front_matter, source_scan
from lib.generator_tool import STRUCTURE_KEYS

TEMPLATE_SUFFIX = '.j2'         # the template of a page index.html is index.html.j2


def is_template(name):
    """Whether a file is the template of a page (index.html.j2)."""
    return name.endswith('.html' + TEMPLATE_SUFFIX)


PAGE_CONFIG = 'config.yaml'      # settings of the pages of a directory


def is_build_input(name):
    """A file of the sources that the build reads and that is not content:
    the template of a page, and the configuration of a directory (it holds
    the settings an author writes for themselves). Never copied into the
    site."""
    return is_template(name) or name == PAGE_CONFIG


def html_name(name):
    """index.html.j2 -> index.html (other names unchanged)"""
    return name[:-len(TEMPLATE_SUFFIX)] if is_template(name) else name


def template_name(name):
    """index.html -> index.html.j2"""
    return name + TEMPLATE_SUFFIX


@dataclass(frozen=True)
class Source:
    name: str | None            # None: the project itself
    root: Path                  # absolute directory

    def __post_init__(self):
        object.__setattr__(self, 'root', Path(self.root))

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
        return self.source.root / self.directory / self.template

    @cached_property
    def text(self):
        """Its source, read once by the scanners (titles, lint, credits...)."""
        return read_text(self.src)

    @cached_property
    def front_matter(self):
        """The settings the page writes about itself, in YAML at its top:

            ---
            layout: stack
            ---
            = Title

        A page says what it is without a Jinja statement
        ({% set layout = 'stack' %}) or a config.yaml sitting next to it for
        one page out of five (lib/front_matter.py)."""
        try:
            return front_matter.split(self.text)[1]
        except ValueError as exc:                   # malformed YAML: named with its page
            raise ValueError(f"'{Path(self.src).as_posix()}': {exc}") from None

    @cached_property
    def scan(self):
        """Its zones and its text read as LHTML (lib/source_scan.py), computed once."""
        return source_scan.Scan(self.text)

    @property
    def settings(self):
        """Its settings, from the least specific to the most: the config.yaml
        of its directory, the front matter of the page itself, then its deck
        entry - the deck is where a talk is arranged, so it has the last
        word over what a page says about itself."""
        return {**self.config, **self.front_matter, **self.meta}

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
        path = os.path.join(directory, PAGE_CONFIG)
        config = {}
        if os.path.isfile(path):
            config = read_yaml(path) or {}
            if not isinstance(config, dict) or any(not isinstance(key, str) for key in config):
                raise ValueError(f"Invalid page configuration '{path}': expected key: value pairs")
            reserved = sorted(set(config) & STRUCTURE_KEYS)
            if reserved:
                raise ValueError(f"Invalid page configuration '{path}': reserved key(s) "
                                 f"{', '.join(reserved)} (written by the generator in structure.yaml)")
        cache[directory] = config
    return cache[directory]


def hidden(path_local, filename):
    """Whether a page is hidden: its file, or any directory above it in the
    source, starts with a dot. Such a page is a draft of the author - it is
    not copied into the site, so it is not generated either."""
    return any(part.startswith('.') for part in (path_local or '').split('/') + [filename] if part)


def discover(source, exclude=(), include_hidden=False):
    """Pages of a source, in file order, with the config.yaml of their
    directory, and the directories `exclude` (the site) left out.

    A hidden page (its file, or a directory above it, starts with a dot) is
    a draft: it is not part of the pages of a project, since it is not
    copied into the site either. `include_hidden` keeps them, for a deck:
    naming one is the choice of its author."""
    cache = {}
    found = find_files_in_hierarchy(source.root, is_template, exclude=exclude)
    if not include_hidden:
        found = [(local, name) for local, name in found if not hidden(local, name)]
    return [Page(source, local, name, position=k, config=_read_config(source.root / local, cache))
            for k, (local, name) in enumerate(found)]


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
    hidden = ignore_hidden(source_dir, skip=is_build_input)
    top = os.path.abspath(source_dir)

    def ignore(directory, names):
        skipped = hidden(directory, names)
        if os.path.abspath(directory) == top:
            skipped |= {n for n in names if os.path.isdir(os.path.join(directory, n))
                        and any(is_template(f) for _, _, files in os.walk(os.path.join(directory, n))
                                for f in files)}
        return skipped
    return copy_tree(source_dir, target_dir, ignore)


def place(pages, site_directory, project_assets=False, source_transform=None):
    """Copy the templates of the pages into the site, with the assets of their
    directory for the pages of other projects (those of the project are copied
    with its whole directory), and of the project too with `project_assets`
    (--only: the sources are not copied). `source_transform(text, source)`:
    applied to the templates (source map). Returns the warnings."""
    site = Path(site_directory)
    real_site = site.resolve()
    copied, warnings = set(), []
    for page in pages:
        target_dir = site / page.site_directory
        if not target_dir.resolve().is_relative_to(real_site):
            raise ValueError(f"'{target_dir}' leads out of the site directory (symbolic link?): "
                             f"refusing to write {page.label} there")
        target_dir.mkdir(parents=True, exist_ok=True)
        if (page.source.name or project_assets) and page.site_directory not in copied:
            warnings += copy_assets(str(page.src.parent), str(target_dir))
            copied.add(page.site_directory)
        if source_transform is None:
            shutil.copy2(page.src, site / page.site_template)
        else:
            with open(site / page.site_template, 'w', encoding='utf-8', newline='\n') as fid:
                fid.write(source_transform(page.text, page.src))
    return warnings
