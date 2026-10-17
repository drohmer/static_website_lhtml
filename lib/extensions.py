"""The extensions of a project (`plugin:` of the configuration): transformations.

An extension is a Python file defining some of these functions:

    prepare(context)                      once per build, before the pages
    pre_process(text, context) -> text    the template of a page, before Jinja
    mid_process(html, context) -> html    the page as Jinja wrote it, before LHTML
    post_process(html, context) -> html   the page once converted, before the menu

It receives content and returns content; the build reads and writes the
files, in the site only. `context` holds what it may read:

    context.options            `plugin_arg` of the configuration
    context.config_directory   the directory the paths of the configuration are relative to
    context.page               the page (title, dir, filename, src, its settings),
                               None in prepare
    context.warning(message)   a warning at the page (at the configuration in prepare)

An exception fails the page, named with the extension; the build goes on
with the other pages and fails at the end.

What this contract is not: a sandbox. An extension is Python and may still
reach the file system; it no longer has to, the ones of the generator do
not, and a write outside the contract is a deviation one can point at. The
hooks of version 2, `pre_process(meta)` and the like, are refused by name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import importlib.util
import inspect
from pathlib import Path
from typing import Any

from lib import filesystem
from lib.structure import built_pages, page_path, template_path

PAGE_STAGES = ('pre_process', 'mid_process', 'post_process')


@dataclass(frozen=True)
class Context:
    options: dict
    config_directory: Path
    page: dict | None = None
    _warn: Any = field(default=None, repr=False)

    def warning(self, message):
        self._warn(message)


class ExtensionError(Exception):
    """An extension written for another contract (the hooks of version 2)."""


def load(path):
    """The module of an extension, checked against the contract."""
    spec = importlib.util.spec_from_file_location('extension_' + Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    name = Path(path).name
    for stage in ('prepare',) + PAGE_STAGES:
        hook = getattr(module, stage, None)
        if hook is None:
            continue
        expected = 1 if stage == 'prepare' else 2
        try:
            count = len(inspect.signature(hook).parameters)
        except (TypeError, ValueError):
            continue
        if count != expected:
            form = 'prepare(context)' if stage == 'prepare' else f'{stage}(text, context) -> text'
            raise ExtensionError(f'{name}: {stage} takes {count} argument(s); an extension defines '
                                 f'{form}, and the build writes the files (the hooks {stage}(meta) of '
                                 f'version 2 are gone, see lib/extensions.py)')
    return module


class Extensions:
    """The extensions of one build, loaded once: a module keeps its state
    from a stage to the next, not from a build to the next (--watch)."""

    def __init__(self, paths):
        self.modules = [(Path(path).name, load(path)) for path in paths]

    def run(self, stage, meta, log):
        """Run `stage` of each extension. Returns the number of failures."""
        options = copy.deepcopy(meta.get('plugin_arg') or {})
        config_directory = Path(meta['config_directory'])
        failures = 0
        for name, module in self.modules:
            hook = getattr(module, stage, None)
            if hook is None:
                continue
            log.detail(f'{name}: {stage}')
            if stage == 'prepare':
                context = Context(options, config_directory, None,
                                  lambda message, name=name: log.warning(f'{name}: {message}'))
                try:
                    hook(context)
                except Exception as exc:
                    log.error(f'{name}: {type(exc).__name__}: {exc}')
                    failures += 1
                continue
            for entry in built_pages(meta):
                path = template_path(meta, entry) if stage == 'pre_process' \
                    else meta['site_directory'] / page_path(entry)
                if not path.is_file():          # the page failed before
                    continue
                place = filesystem.shown(entry.get('src', path))
                context = Context(options, config_directory, copy.deepcopy(entry),
                                  lambda message, name=name, place=place: log.warning(f'{name}: {message}', place))
                text = path.read_text(encoding='utf-8')
                try:
                    result = hook(text, context)
                    if not isinstance(result, str):
                        raise TypeError(f'{stage} returned {type(result).__name__}, not the text of the page')
                except Exception as exc:
                    log.error(f'{name}: {stage}: {type(exc).__name__}: {exc}', place)
                    failures += 1
                    continue
                if result != text:
                    with open(path, 'w', encoding='utf-8', newline='\n') as fid:
                        fid.write(result)
        return failures
