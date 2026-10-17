"""A project is decks, each built to targets.

    source_directory: src
    site_directory: _site
    decks: directories            # each directory of src/ is a deck
    targets:
      html: {theme: slides}
      pdf: {theme: slides-pdf}    # a theme with export: pdf (lib/pdf_export.py)

A deck is a directory of the sources (src/01_procedural/), built as a site
of its own; a target is a theme it is built with. The site of a deck for a
target is <site>/<deck>/<target>/, and an export (the PDF) lands in
<site>/<deck>/, named after the deck. Without `decks`, the project is one
deck (the sources); without `targets`, one target (`theme`), built into the
site directory itself: a project of one site is a project of one deck.

`plan` turns a configuration into the list of these builds, each with its
own configuration; the build of one of them is the build of a site.
"""
from dataclasses import dataclass, replace
from pathlib import Path

from lib import theme
from lib.configuration import ConfigError, Config


@dataclass(frozen=True)
class Build:
    deck: str | None            # None: the project is one deck
    target: str | None          # None: one target, the theme of the configuration
    config: Config              # the configuration of this build
    only: list | None = None    # --only pointers inside the deck, None for all its pages

    @property
    def label(self):
        return ' '.join(f'{kind} {name}' for kind, name in (('deck', self.deck), ('target', self.target)) if name)

    @property
    def scope(self):
        """Where the state of this build is kept, under .verification/, .layout/
        and .structure/: '<deck>/<target>', '' for a project of one site."""
        return '/'.join(name for name in (self.deck, self.target) if name)

    @property
    def export_name(self):
        """The name of the PDF of the deck."""
        return self.deck or 'slides'


def decks(config):
    """The names of the decks, in order, or [None] for a project of one deck."""
    if config.decks != 'directories':
        return [None]
    return sorted(d.name for d in config.source_directory.iterdir()
                  if d.is_dir() and not d.name.startswith(('.', '_')))


def plan(config, only=None, targets=None):
    """The builds of a project: each deck for each target, in that order.

    only: --only pointers. With decks, a pointer names a deck (01_procedural)
        or pages of it (01_procedural/03_noise); only the decks named are built.
    targets: the names of the targets to build (--target), all by default."""
    names = decks(config)
    if not names:
        raise ConfigError(f"decks: directories: '{config.source_directory.as_posix()}' has no deck "
                          f"(a directory of pages)")
    chosen = dict(config.targets or {None: None})
    if targets:
        unknown = sorted(set(targets) - set(chosen))
        if unknown:
            known = ', '.join(t for t in chosen if t) or 'none: the project has no targets'
            raise ConfigError(f"--target {', '.join(unknown)}: unknown target (known: {known})")
        chosen = {name: spec for name, spec in chosen.items() if name in targets}

    pointers = {name: None for name in names}
    if only and names != [None]:
        pointers = {}
        for pointer in only:
            deck, _, inside = pointer.strip('/').partition('/')
            if deck not in names:
                raise ConfigError(f"--only {pointer}: no deck '{deck}' (decks: {', '.join(names)})")
            if not inside:
                pointers[deck] = None
            elif pointers.get(deck, []) is not None:
                pointers.setdefault(deck, []).append(inside)
    elif only:
        pointers = {None: list(only)}

    exports = [name for name, spec in chosen.items() if spec and theme.read(spec['theme'])['export']]
    if len(exports) > 1:            # they would write the same <deck>.pdf and images/
        raise ConfigError(f"targets {', '.join(exports)}: each exports a PDF to the same place "
                          f"(<site>/<deck>/<deck>.pdf); keep one, or build them in two configurations")
    result = []
    for deck in names:
        if deck not in pointers:
            continue
        for target, spec in chosen.items():
            source, site = config.source_directory, config.site_directory
            cache = config.cache_video_directory
            if deck is not None:
                source, site = source / deck, site / deck
                cache = cache / deck if cache else None
            changes = {'source_directory': source, 'site_directory': site, 'cache_video_directory': cache}
            if target is not None:
                changes.update(site_directory=site / target, theme=spec['theme'])
            elif deck is not None and theme.read(config.theme)['export']:
                # the export lands next to the site it renders: in the directory of the deck
                changes.update(site_directory=site / 'pdf')
            _check_destination(config.site_directory, changes['site_directory'])
            result.append(Build(deck, target, replace(config, **changes), pointers[deck]))
    return result


def _check_destination(site, destination):
    """A build replaces its destination: it must be a directory of the site
    itself. None of the directories between the site and it may be a
    symbolic link (.site/01_a/html -> src/01_a would have the build replace
    the sources), nor may it resolve outside the site."""
    site, destination = Path(site), Path(destination)
    path = destination
    while path != site and site in path.parents:
        if path.is_symlink():
            raise ConfigError(f"Unsafe output: '{path.as_posix()}' is a symbolic link; the build would "
                              f"replace what it points to ({path.resolve().as_posix()})")
        path = path.parent
    resolved, root = destination.resolve(), site.resolve()
    if resolved != root and root not in resolved.parents:
        raise ConfigError(f"Unsafe output: '{destination.as_posix()}' resolves outside the site "
                          f"directory ({resolved.as_posix()})")
