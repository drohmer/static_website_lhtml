"""What a theme declares about the build, in `<theme>/theme.yaml`.

A theme is the third party the build kept consulting without asking: which
template a page is wrapped in and which block it fills, and what the
measurement must take as the content of a page. Those answers were written
in the engine and in an extension - `theme/template/base.html` in
`plugins/auto_wrap.py`, `root: 'body'` and `exclude: 'nav, footer'` among
the defaults of `lib/layout_options.py`, which are the answers of the
`slides` theme for all three themes shipped here. A project using another
theme had to know them and restate them in its own configuration.

The manifest:

    template: 'theme/template/base.html'   # the page is wrapped in it
    content_block: 'content'               # the Jinja block it fills
    toc:                                   # the theme has a menu
      file: 'js/menu.js'                   # it receives the table of contents
      keys: [duration]                     # extra page settings it carries
    layout:                                # what the measurement reads
      root: 'body'                         # CSS selector of the content
      exclude: 'nav, footer'               # children of the root that are not
      width: 1920                          # size of a page, in CSS pixels
      height: 1080

A theme with no `toc:` has no menu, and the build writes none. That is how
a theme says so - not a switch in a project's configuration, which has no
way of knowing.

Everything is optional, and a theme with no manifest builds as before.
What it declares replaces the defaults of the engine, and the `layout:` key
of a project replaces both: engine, then theme, then project. The project
keeps the last word because it is the one that knows it added a banner.

`design.yaml` next to it stays what it is - the tokens and the macros an
author writes with. This file is the contract with the build; that one is
the vocabulary of the content.
"""
from pathlib import Path

import yaml

from lib.configuration import ConfigError

MANIFEST = 'theme.yaml'
DEFAULTS = {'template': 'theme/template/base.html', 'content_block': 'content',
            'toc': None, 'layout': {}}
TOC_KEYS = ('file', 'keys')
# The layout keys a theme may declare: the ones that describe the theme, not
# the preferences of a project (thresholds, output directory, jobs...).
LAYOUT_KEYS = ('root', 'exclude', 'width', 'height', 'reserved')


def path(theme_directory):
    return Path(theme_directory) / MANIFEST


def read(theme_directory):
    """The manifest of a theme: the defaults, then what the file says.
    A theme with no theme.yaml gets the defaults."""
    manifest = dict(DEFAULTS)
    file = path(theme_directory)
    if not file.is_file():
        return manifest
    try:
        given = yaml.safe_load(file.read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError) as error:
        raise ConfigError(f'{file}: {error}') from None
    manifest.update(validate(given, file))
    return manifest


def validate(given, file):
    """Check a manifest before the build; returns it. A key the build does
    not know is refused and not ignored: a theme declares a contract, and a
    contract nobody reads is worse than no contract."""
    if not isinstance(given, dict):
        raise ConfigError(f'{file}: expected a mapping of theme settings')
    unknown = sorted(set(given) - set(DEFAULTS))
    if unknown:
        raise ConfigError(f"{file}: unknown theme setting(s) {', '.join(unknown)}; "
                          f"known: {', '.join(sorted(DEFAULTS))}")
    for key in ('template', 'content_block'):
        if key in given and (not isinstance(given[key], str) or not given[key].strip()):
            raise ConfigError(f'{file}: {key} must be a non-empty string')
    toc = given.get('toc')
    if toc is not None:
        if not isinstance(toc, dict) or set(toc) - set(TOC_KEYS):
            raise ConfigError(f"{file}: toc must be a mapping of {', '.join(TOC_KEYS)} "
                              f"(or absent, for a theme with no menu)")
        if not isinstance(toc.get('file', ''), str) or not toc.get('file', '').strip():
            raise ConfigError(f'{file}: toc: file must name the theme file that receives '
                              f'the table of contents')
        keys = toc.get('keys', [])
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise ConfigError(f'{file}: toc: keys must be a list of page setting names')
    layout = given.get('layout', {})
    if not isinstance(layout, dict):
        raise ConfigError(f'{file}: layout must be a mapping')
    unknown = sorted(set(layout) - set(LAYOUT_KEYS))
    if unknown:
        raise ConfigError(f"{file}: layout: a theme does not set {', '.join(unknown)}; "
                          f"it may set {', '.join(LAYOUT_KEYS)}")
    return given


def of(meta):
    """The manifest of the theme of a build."""
    return read(meta['theme'])
