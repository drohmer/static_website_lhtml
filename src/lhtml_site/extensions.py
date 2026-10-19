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

An exception fails the page, named with the extension: the later stages
leave it out, and --only gives it back its previous version; the build goes
on with the other pages and fails at the end. An exception in prepare
keeps that extension away from the pages of the build.

What this contract is not: a sandbox. An extension is Python and may still
reach the file system; it no longer has to, the ones of the generator do
not, and a write outside the contract is a deviation one can point at. The
hooks of static_website_lhtml, `pre_process(meta)` and the like, are refused by name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import importlib.util
import inspect
import traceback
from pathlib import Path
from typing import Any

from lhtml_site import filesystem
from lhtml_site.structure import built_pages, page_path, template_path

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
    """An extension written for another contract (the hooks of static_website_lhtml)."""


def _refusal(name, stage, reason):
    form = 'prepare(context)' if stage == 'prepare' else f'{stage}(text, context) -> text'
    return ExtensionError(f'{name}: {stage} {reason}; an extension defines {form}, and the build '
                          f'writes the files (the hooks {stage}(meta) of static_website_lhtml are gone, see '
                          f'lhtml_site/extensions.py)')


def load(path):
    """The module of an extension, checked against the contract."""
    name = Path(path).name
    spec = importlib.util.spec_from_file_location('extension_' + Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ExtensionError(f'{name}: {type(exc).__name__}: {exc}') from exc
    for stage in ('prepare',) + PAGE_STAGES:
        hook = getattr(module, stage, None)
        if hook is None:
            continue
        try:
            signature = inspect.signature(hook)
        except (TypeError, ValueError):
            continue
        first = next(iter(signature.parameters), None)
        if first == 'meta':
            raise _refusal(name, stage, 'takes meta')
        try:
            signature.bind(*([None] * (1 if stage == 'prepare' else 2)))
        except TypeError:
            raise _refusal(name, stage, f'cannot be called with {1 if stage == "prepare" else 2} '
                                        f'argument(s)') from None
    return module


class Extensions:
    """The extensions of one build, loaded once: a module keeps its state
    from a stage to the next, not from a build to the next (--watch)."""

    def __init__(self, paths):
        self.modules = [(Path(path).name, load(path)) for path in paths]
        self.unprepared = set()         # their prepare failed: their page stages do not run

    def run(self, stage, meta, log):
        """Run `stage` of each extension. Returns (number of failures, the
        entries of the pages that failed): a page that failed leaves the
        build, as one that Jinja or LHTML could not render."""
        config_directory = Path(meta['config_directory'])
        options = meta.get('plugin_arg') or {}
        failures, failed = 0, []
        for name, module in self.modules:
            hook = getattr(module, stage, None)
            if hook is None or name in self.unprepared:
                continue
            log.detail(f'{name}: {stage}')
            if stage == 'prepare':
                place = filesystem.shown(meta.get('config_file') or config_directory)
                context = Context(copy.deepcopy(options), config_directory, None,
                                  lambda message, name=name: log.warning(f'{name}: {message}', place))
                try:
                    hook(context)
                except Exception as exc:
                    log.error(f'{name}: prepare: {type(exc).__name__}: {exc}', place)
                    log.debug(traceback.format_exc())
                    self.unprepared.add(name)
                    failures += 1
                continue
            for entry in built_pages(meta):
                if any(entry is f for f in failed):
                    continue
                path = template_path(meta, entry) if stage == 'pre_process' \
                    else meta['site_directory'] / page_path(entry)
                if not path.is_file():          # the page failed before
                    continue
                place = filesystem.shown(entry.get('src', path))
                context = Context(copy.deepcopy(options), config_directory, copy.deepcopy(entry),
                                  lambda message, name=name, place=place: log.warning(f'{name}: {message}', place))
                text = path.read_text(encoding='utf-8')
                try:
                    result = hook(text, context)
                    if not isinstance(result, str):
                        raise TypeError(f'{stage} returned {type(result).__name__}, not the text of the page')
                except Exception as exc:
                    log.error(f'{name}: {stage}: {type(exc).__name__}: {exc}', place)
                    log.debug(traceback.format_exc())
                    failures += 1
                    failed.append(entry)
                    continue
                if result != text:
                    with open(path, 'w', encoding='utf-8', newline='\n') as fid:
                        fid.write(result)
        return failures, failed
