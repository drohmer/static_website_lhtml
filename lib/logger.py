from rich.console import Console
import time

console = Console()

class Logger:
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

    def debug(self, input):
        if self.debug_level > 1:
            self.display(input)
        
    def title(self, input, pre='\n', post='', indent_level=0):
        self.keyvalue(f'[bold white] {input} [/bold white]',pre=pre,post=post,indent_level=indent_level)

    def ok_elapsed(self):
        elapsed = self.toc()
        self.display(f'[[green]OK[/green]] {elapsed}s',indent_level=1)

    def keyvalue(self, key='info', value='', indent_level=1, debug_level=1, pre='', post=''):
        self.display(f'\[{key}] {value}',indent_level=indent_level, pre=pre, post=post)

    def tic(self):
        self.time_count = time.time()
    def toc(self):
        return round(time.time()-self.time_count,2)

    def error(self, msg):
        self.display(f'[red]\[Error] {msg}', debug_level=0, pre='\n')

    
