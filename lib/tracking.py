"""Templates and LHTML includes read by a build: dependencies of each page.

An optional instrumenter (the agent extension's SourceRegistry) can add source
markers to the included sources; the base build only records the files read.
"""
from contextlib import contextmanager
from pathlib import Path

from jinja2 import BaseLoader


class TrackingLoader(BaseLoader):
    """Instrument source includes/imports without editing their files.

    Built page templates already contain markers. Theme templates are tracked
    as dependencies but not instrumented (their navigation isn't slide content).
    """
    def __init__(self, loader, registry, source_roots):
        self.loader, self.registry = loader, registry
        self.roots = [Path(root).resolve() for root in source_roots]
        self.used = set()

    def get_source(self, environment, template):
        text, filename, uptodate = self.loader.get_source(environment, template)
        if filename:
            path = Path(filename).resolve()
            self.used.add(str(path))
            if self.registry and any(root == path or root in path.parents for root in self.roots):
                text = self.registry.instrument(text, path)
        return text, filename, uptodate


@contextmanager
def lhtml_includes(registry, used):
    """Instrument recursive text includes; code/verbatim includes stay untouched.

    LHTML exposes no source-loader hook yet. This scoped adapter restores its
    function even when conversion fails. Generator builds are single-threaded.
    """
    from lhtml import process
    original = process.process_include_recursive
    original_read = process.read_source

    def tracked(text, directories, stores, _stack=()):
        if _stack:
            used.add(str(Path(_stack[-1]).resolve()))
            if registry:
                full_text = original_read(_stack[-1])
                text = registry.instrument(text, _stack[-1], original_text=full_text)
        return original(text, directories, stores, _stack)

    def read_tracked(filename):
        used.add(str(Path(filename).resolve()))
        return original_read(filename)

    process.read_source = read_tracked
    process.process_include_recursive = tracked
    try:
        yield
    finally:
        process.process_include_recursive = original
        process.read_source = original_read
