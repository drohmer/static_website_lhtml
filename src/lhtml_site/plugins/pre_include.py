"""Text written at the top of every page: the files of `plugin_arg: pre_include:`
(Jinja macros shared by the pages, for instance), relative to the configuration.

    plugin: ['plugins/pre_include.py']
    plugin_arg:
      pre_include: ['local_plugins/macro.html']
"""
from pathlib import Path

_included = ''


def prepare(context):
    global _included
    _included = '\n'.join(Path(context.config_directory, f).read_text(encoding='utf-8')
                          for f in context.options.get('pre_include', []))


def pre_process(text, context):
    return _included + '\n' + text
