from rich.console import Console # pip3 install rich
from rich.markup import escape as rich_escape
import time

console = Console()


def escape(text):
    """`text` shown as written in rich markup (rich_escape doubles a final
    backslash, which is only needed before a tag)."""
    return rich_escape(str(text) + ' ')[:-1]

class Logger:
    """Log of the build. The messages of display, keyvalue and title may hold
    rich markup ([bold]...); the values of keyvalue and the messages of
    warning and error are shown as written (a path or the output of a
    command may contain [ ])."""

    def __init__(self, indent_level_base=0, debug_level=1):
        self.indent_level_base = indent_level_base
        self.debug_level = debug_level
        self.time_count = 0

    def display(self, input='', indent_level=0, debug_level=1, pre='', post=''):
        if debug_level<=self.debug_level:
            indent = '\t'*(self.indent_level_base+indent_level)
            console.print(pre,end='')
            console.print(indent+input)
            console.print(post,end='')

    def plain(self, text=''):
        """A line as written (no markup, no indentation): lint findings, summaries."""
        print(text, flush=True)

    def debug(self, input):
        if self.debug_level > 1:
            self.display(escape(str(input)))

    def title(self, input, pre='\n', post='', indent_level=0):
        self.display(f'[[bold white] {escape(input)} [/bold white]] ', pre=pre, post=post, indent_level=indent_level)

    def ok_elapsed(self):
        elapsed = self.toc()
        self.display(f'[[green]OK[/green]] {elapsed}s',indent_level=1)

    def keyvalue(self, key='info', value='', indent_level=1, debug_level=1, pre='', post=''):
        """`value` preceded by `[key]` (no prefix for the key 'info')."""
        prefix = '' if key == 'info' else escape(f'[{key}]') + ' '
        self.display(prefix + escape(value), indent_level=indent_level,
                     debug_level=debug_level, pre=pre, post=post)

    def tic(self):
        self.time_count = time.time()
    def toc(self):
        return round(time.time()-self.time_count,2)

    def error(self, msg):
        self.display(f'[red] [Error] {escape(str(msg))}', debug_level=0, pre='\n')

    def warning(self, msg):
        self.display(f'[yellow] [Warning] {escape(str(msg))}', debug_level=0, pre='\n')
