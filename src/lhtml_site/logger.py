"""What a build prints.

A problem is one line, `place: level: message`, the place being
`file:line:column` as far as it is known (lhtml_site/source_map.place). A build
ends with one line saying what it built (generate.py). The stages and their
time print with -v, the details for debugging with -d. A line is never cut,
and is coloured on a terminal only.
"""
from contextlib import contextmanager
import time

from rich.console import Console     # pip3 install rich

console = Console(soft_wrap=True, highlight=False, emoji=False)     # a message as written: no :fire:
STYLES = {'error': 'bold red', 'warning': 'yellow'}


class Logger:
    def __init__(self, verbose=False, debug=False):
        self.verbose = verbose or debug
        self.debugging = debug
        self.counts = {'warning': 0, 'error': 0}

    def _print(self, text, style=None):
        console.print(text, style=style, markup=False)

    def info(self, message=''):
        """What the author is told whatever the options: an output written, a summary."""
        self._print(str(message))

    def detail(self, message):
        """A step of the build (-v)."""
        if self.verbose:
            self._print('  ' + str(message))

    def debug(self, message):
        if self.debugging:
            self._print(str(message))

    def problem(self, level, message, place=None):
        self.counts[level] += 1
        self._print(f'{place}: {level}: {message}' if place else f'{level}: {message}', STYLES[level])

    def warning(self, message, place=None):
        self.problem('warning', message, place)

    def error(self, message, place=None):
        self.problem('error', message, place)

    @contextmanager
    def progress(self, description, total):
        """A bar for a long step of `total` items, on a terminal only (a log
        gets nothing), gone once done: yields the function to call per item."""
        if not console.is_terminal:
            yield lambda: None
            return
        from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
        with Progress(TextColumn('{task.description}'), BarColumn(), MofNCompleteColumn(), TimeElapsedColumn(),
                      console=console, transient=True) as bar:
            task = bar.add_task(description, total=total)
            yield lambda: bar.advance(task)

    @contextmanager
    def stage(self, title):
        """A stage of the build: its title and its time, with -v."""
        if self.verbose:
            self._print(title)
        start = time.time()
        yield
        self.detail(f'{time.time() - start:.2f}s')
