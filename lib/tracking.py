"""Templates read by a build: the files each page depends on, for --only
(lib/dependencies.py). LHTML reads no file (LHTML 3), so Jinja's loader is
the only reader to track."""
from pathlib import Path

from jinja2 import BaseLoader


class TrackingLoader(BaseLoader):
    """A Jinja loader that records the files it reads: the templates a page
    extends or includes are dependencies of that page.

    `mark(text, path)`: the source map (lib/source_map.py), applied to the
    templates of the project only. The pages are marked before the build
    writes them into the site; what they include is read here, and is marked
    here, so its blocks name the file they are written in instead of taking
    a line of the page. The theme's templates are not under a source root
    and stay unmarked."""
    def __init__(self, loader, source_roots, mark=None):
        self.loader = loader
        self.roots = [Path(root).resolve() for root in source_roots]
        self.used = set()
        self.mark = mark

    def get_source(self, environment, template):
        text, filename, uptodate = self.loader.get_source(environment, template)
        if filename:
            path = Path(filename).resolve()
            self.used.add(str(path))
            # Markers are LHTML's: a Markdown file keeps its text (lib/markdown_page.py)
            if (self.mark and not path.name.endswith(('.md', '.md.j2'))
                    and any(path.is_relative_to(root) for root in self.roots)):
                text = self.mark(text, str(path))
        return text, filename, uptodate
