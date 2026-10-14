"""Templates and LHTML includes read by a build: the files each page
depends on, for --only (lib/dependencies.py)."""
from contextlib import contextmanager
from pathlib import Path

from jinja2 import BaseLoader


class TrackingLoader(BaseLoader):
    """A Jinja loader that records the files it reads: the templates a page
    extends or includes are dependencies of that page."""
    def __init__(self, loader, source_roots):
        self.loader = loader
        self.roots = [Path(root).resolve() for root in source_roots]
        self.used = set()

    def get_source(self, environment, template):
        text, filename, uptodate = self.loader.get_source(environment, template)
        if filename:
            path = Path(filename).resolve()
            self.used.add(str(path))
        return text, filename, uptodate


@contextmanager
def lhtml_includes(used):
    """Record the text includes LHTML reads; code and verbatim includes stay
    untouched.

    LHTML exposes no source-loader hook yet. This scoped adapter restores its
    function even when conversion fails. Generator builds are single-threaded.
    """
    from lhtml import process
    original = process.process_include_recursive
    original_read = process.read_source

    def tracked(text, directories, stores, _stack=()):
        if _stack:
            used.add(str(Path(_stack[-1]).resolve()))
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
