"""User configuration, its validation, and the meta of a build."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import difflib
import os
import re

from lib.filesystem import read_yaml
from lib.structure import PRIVATE_KEYS

GENERATOR_DIRECTORY = Path(__file__).resolve().parents[1]
RENAMED_DIRECTORIES = {'theme_templates': 'themes', 'src_site_example': 'example'}   # in 3.0


# Keys of meta set by the generator during a build (never by the configuration)
# Plugins of the previous version that the build now runs itself: the name of
# the file, and what it became.
CORE_STAGES = {
    'menu.py': "the theme's menu",
    'title_submenu.py': 'the heading ids (configuration key title_id:)',
    'auto_wrap.py': 'the wrapping of a page in the template of its theme',
    'auto-wrap.py': 'the wrapping of a page in the template of its theme',
    'redirection_first_page.py': 'the index of a site that has none',
    'cache_video.py': "the transcoded videos (set 'cache_video_directory:' to ask for them)",
    'generate_pdf.py': "the PDF export, a target now (targets: pdf: {theme: slides-pdf})",
}

RUNTIME_KEYS = frozenset((
    'args', 'log', 'plugin_paths', 'config_file', 'config_directory', 'lib_directory',
    'published_site_directory',     # the site, while the build is made in a staging directory
    'exported',                     # the file an export wrote (lib/pdf_export.py)
    'only',                         # --only: the build is made in the site, for some pages
    'structure', 'built',           # all the pages of the site / those generated (lib/structure.py)
    'previous_pages',               # --only: HTML of the pages before the build (restored if they fail)
    'strict',                       # --strict: the check of the warnings, before the pages are kept
    'loaded_design', 'macros',      # the design (lib/design.py) and its macros for LHTML
    'lint_findings',                # {source path: [finding]} of the generated pages (lib/lint.py)
    'measure',                      # --only: the pages the layout report measures again
    'source_roots',                 # the sources read by each page (lib/tracking.py)
    'dependency_contexts', 'dependency_store', 'dependency_measure',
    'template_dependencies',        # what each page depends on (lib/dependencies.py)
    '_dependency_engine', '_dependency_theme_scopes',   # the same for all its pages: read once
    'analyse_layout',               # --layout: the build runs the layout analysis (lib/layout/build.py)
    'publish_site',                 # a target asks for its intermediate site not to be published
    'source_map', 'feedback',       # builds for development (lib/source_map.py, lib/feedback.py)
    'planned_slides',               # entries of the deck without a source yet
    'export_name',                  # the name of the PDF of a deck (lib/pdf_export.py)
    'build_scope',                  # <deck>/<target>: where its state is kept (lib/project.py)
))


class ConfigError(ValueError):
    """An actionable configuration error, displayed without a traceback."""


@dataclass(frozen=True)
class Config:
    # Directories: as written in the YAML, absolute Paths once load_config resolved them
    source_directory: Path | str = 'src_site'
    site_directory: Path | str = '.site'
    theme: Path | str = str(GENERATOR_DIRECTORY / 'themes/webpage-frame')
    # Extensions, and nothing else: everything a bundled theme needs to
    # render a project written in LHTML is a stage of the build now
    # (lib/wrap.py, lib/headings.py, lib/menu.py, lib/index_page.py), so the
    # default is empty and a project lists only what is its own.
    plugin: list[str] = field(default_factory=list)
    debug: bool = False
    title_id: bool = True
    keywords: dict = field(default_factory=dict)
    use_tidy: bool = False
    line_breaks: bool = False       # 'line-breaks:' in the YAML, as LHTML spells it
    # Page settings a custom theme needs in the site, beyond the ones the
    # bundled themes display (lib/structure.py, PUBLIC_KEYS). Everything else
    # an author writes in a config.yaml or a deck entry stays out of the site.
    public_page_keys: list[str] = field(default_factory=list)
    plugin_arg: dict = field(default_factory=dict)
    layout: dict = field(default_factory=dict)      # options of the layout analysis (--layout)
    cache_video_directory: Path | str | None = None
    chrome: str | None = None
    design: dict | str | None = None
    deck: list | dict | str | None = None
    # A project of several decks, each built to several targets (lib/project.py):
    # 'directories' (each directory of the sources is a deck), and
    # {name: {theme: directory}}, the themes resolved to Paths by load_config
    decks: str | None = None
    targets: dict | None = None

    def to_meta(self):
        values = asdict(self)
        for key in ('cache_video_directory', 'chrome', 'design', 'deck', 'decks', 'targets'):
            if values[key] is None:
                del values[key]
        return values


@dataclass
class BuildContext:
    config: Config
    config_file: Path
    args: Any
    log: Any
    plugin_paths: list[str] = field(default_factory=list)
    meta: dict = field(init=False)

    def __post_init__(self):
        # The state of a build: a copy, which never changes the configuration
        self.meta = self.config.to_meta()
        self.meta.update(config_file=str(self.config_file),
                         config_directory=self.config_file.parent,
                         lib_directory=GENERATOR_DIRECTORY,
                         args=self.args, log=self.log,
                         plugin_paths=self.plugin_paths)


def _file_or_inline(values, key, inline_types, inline_text, config_directory):
    """A key given as the path of a YAML file (resolved from the configuration
    directory, must exist) or inline (mapping with string keys / list)."""
    value = values.get(key)
    if value is None:
        return
    if isinstance(value, str) and value.strip():
        file = Path(value).expanduser()
        if not file.is_absolute():
            file = config_directory / file
        if not file.is_file():
            raise ConfigError(f"'{key}' file not found: '{file}'")
        values[key] = str(file.resolve())
    elif not isinstance(value, inline_types) or (isinstance(value, dict)
                                                 and any(not isinstance(k, str) for k in value)):
        raise ConfigError(f"'{key}' must be {inline_text} or the path of a YAML file")


def _chrome_executable(values, config_directory):
    """'chrome': the Chrome executable the Node scripts run (layout report,
    PDF export, --render), instead of the one downloaded by puppeteer. A
    relative path is resolved from the configuration directory; a macOS
    bundle ('.app') is resolved to the executable it contains."""
    value = values.get('chrome')
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("'chrome' must be the path of the Chrome executable")
    file = Path(value.strip()).expanduser()
    if not file.is_absolute():
        file = config_directory / file
    if file.suffix == '.app' and file.is_dir():                 # macOS bundle
        inside = file / 'Contents/MacOS' / file.stem
        if not inside.is_file():
            candidates = sorted(p for p in (file / 'Contents/MacOS').glob('*') if p.is_file())
            if not candidates:
                raise ConfigError(f"'chrome': no executable in the bundle '{file}'")
            inside = candidates[0]
        file = inside
    if not file.is_file():
        raise ConfigError(f"'chrome' executable not found: '{file}'")
    if not os.access(file, os.X_OK):
        raise ConfigError(f"'chrome' is not executable: '{file}'")
    values['chrome'] = str(file.resolve())


TARGET_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]*$')


def theme_directory(value, config_directory):
    """A theme given as a directory (relative to the configuration) or as the
    name of a theme of the generator ('slides')."""
    directory = Path(value).expanduser()
    if not directory.is_absolute():
        directory = config_directory / directory
    if not directory.is_dir() and (GENERATOR_DIRECTORY / 'themes' / value).is_dir():
        directory = GENERATOR_DIRECTORY / 'themes' / value
    return directory.resolve()


def _decks_and_targets(values, data, config_directory):
    """'decks' and 'targets' (lib/project.py), checked, the themes resolved."""
    if values.get('decks') is not None and values['decks'] != 'directories':
        raise ConfigError("'decks' must be 'directories' (each directory of the sources is a deck)")
    targets = values.get('targets')
    if targets is None:
        return
    if not isinstance(targets, dict) or not targets:
        raise ConfigError("'targets' must map a name to its settings, e.g. html: {theme: slides}")
    if 'theme' in data:
        raise ConfigError("'theme' and 'targets' together: give the theme of each target")
    resolved = {}
    for name, spec in targets.items():
        if not isinstance(name, str) or not TARGET_NAME.match(name):
            raise ConfigError(f"'targets': invalid name {name!r} (letters, digits, - and _)")
        if name == 'images':
            raise ConfigError("'targets': 'images' is where the PDF export writes the slide images; "
                              "choose another name")
        if not isinstance(spec, dict) or set(spec) != {'theme'} or not isinstance(spec['theme'], str):
            raise ConfigError(f"'targets': {name}: expected {{theme: <theme>}}")
        theme = theme_directory(spec['theme'], config_directory)
        if not theme.is_dir():
            raise ConfigError(f"'targets': {name}: theme not found '{spec['theme']}'")
        resolved[name] = {'theme': theme}
    values['targets'] = resolved


def load_config(filename, debug_override=None):
    path = Path(filename).expanduser().resolve()
    warnings = []
    if not path.exists() and path.name == 'configure_default.yaml':
        raise ConfigError("'configure_default.yaml' was renamed 'configure_example.yaml' (3.0): "
                          "update your command")
    try:
        data = read_yaml(path)
    except ValueError as exc:                       # the message names the file
        raise ConfigError(str(exc)) from None
    if data is None:
        data = {}
    if not isinstance(data, dict) or any(not isinstance(k, str) for k in data):
        raise ConfigError('Configuration must contain named key: value pairs')

    if 'line-breaks' in data:                       # the spelling of LHTML
        data['line_breaks'] = data.pop('line-breaks')
    if 'plugin_post' in data:
        raise ConfigError("'plugin_post' was removed (3.0): list its plugins under 'plugin' "
                          "(all their hooks are run)")
    if 'level_print' in data:
        raise ConfigError("'level_print' was removed (3.0): the build prints no indented log "
                          "(-v shows its stages)")
    if 'include_head' in data:
        raise ConfigError("'include_head' was removed (3.0): it was read nowhere; a theme "
                          "places what goes in <head>")

    defaults = Config().to_meta()
    known = set(defaults) | {'cache_video_directory', 'chrome', 'design', 'deck', 'decks', 'targets'}
    for key in sorted(set(data) - known):
        if key in RUNTIME_KEYS:
            raise ConfigError(f"'{key}' is runtime state and cannot be set in YAML")
        suggestion = difflib.get_close_matches(key, sorted(known), n=1)
        hint = f" Did you mean '{suggestion[0]}'?" if suggestion else ''
        warnings.append(f"Unknown configuration key '{key}', ignored.{hint} "
                        f"(A plugin reads its options in 'plugin_arg'.)")
    values = {**defaults, **{k: v for k, v in data.items() if k in known}}
    for key in ('debug', 'title_id', 'use_tidy', 'line_breaks'):
        if type(values[key]) is not bool:
            raise ConfigError(f"'{key}' must be a boolean (true or false)")
    for key in ('keywords', 'plugin_arg', 'layout'):
        if not isinstance(values[key], dict) or any(not isinstance(k, str) for k in values[key]):
            raise ConfigError(f"'{key}' must be a mapping with string keys")
    for name in sorted({'params', 'page', 'credit', 'credits'} & set(values['keywords'])):
        raise ConfigError(f"'keywords': '{name}' is reserved (Jinja variable of the generator: "
                          f"params, the deck parameters of a page; page, its metadata; credit, credits)")
    plugins = values['plugin']
    if isinstance(plugins, str):
        plugins = [plugins]
    elif plugins is None:
        plugins = []
    values['plugin'] = plugins
    for key in ('plugin', 'public_page_keys'):
        if not isinstance(values[key], list) or any(not isinstance(v, str) or not v.strip() for v in values[key]):
            raise ConfigError(f"'{key}' must be a list of non-empty strings")
    for name in sorted(set(values['public_page_keys']) & set(PRIVATE_KEYS)):
        raise ConfigError(f"'public_page_keys': '{name}' is never written into the site "
                          f"(it is the path of the source on this machine)")
    # The layout analysis is part of the generator, not a plugin: it is
    # selected by --layout and configured by 'layout:'. A configuration of
    # the previous version says so here, before the build, naming the fix.
    for entry in plugins:
        if entry.endswith('layout_report.py'):
            raise ConfigError("'plugin': the layout report is no longer a plugin. Remove "
                              f"'{entry}' from 'plugin:' and run the build with --layout")
    if isinstance(values['plugin_arg'], dict) and 'layout_report' in values['plugin_arg']:
        raise ConfigError("'plugin_arg': the options of the layout report moved to the "
                          "configuration key 'layout:'. Move the content of "
                          "'plugin_arg: layout_report:' under 'layout:'")
    # Stages the build always runs: a project does not list them, and cannot
    # know whether its theme has a menu - the theme declares that (theme.yaml).
    for entry in plugins:
        name = entry.rsplit('/', 1)[-1]
        if name in CORE_STAGES:
            raise ConfigError(f"'plugin': {CORE_STAGES[name]} is a stage of the build, not a "
                              f"plugin. Remove '{entry}' from 'plugin:'")
    if isinstance(values['plugin_arg'], dict) and 'menu' in values['plugin_arg']:
        raise ConfigError("'plugin_arg': the extra page settings of the menu are declared by "
                          "the theme. Move the content of 'plugin_arg: menu: keys:' to "
                          "'toc: keys:' in the theme.yaml of your theme")

    _chrome_executable(values, path.parent)
    _decks_and_targets(values, data, path.parent)

    _file_or_inline(values, 'design', dict, 'a mapping (tokens, macros)', path.parent)
    _file_or_inline(values, 'deck', (list, dict), 'a list of slides', path.parent)

    for key in ('source_directory', 'site_directory', 'theme', 'cache_video_directory'):
        if key not in values:
            continue
        value = values[key]
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"'{key}' must be a non-empty directory path")
        directory = Path(value).expanduser()
        if not directory.is_absolute():
            directory = path.parent / directory
        if key == 'theme':          # a directory, or the name of a theme of the generator
            directory = theme_directory(value, path.parent)
        if key in ('source_directory', 'theme') and not directory.is_dir():
            renamed = Path(*[RENAMED_DIRECTORIES.get(part, part) for part in directory.parts])
            if renamed.is_dir():
                raise ConfigError(f"'{key}': '{directory.as_posix()}' was renamed "
                                  f"'{renamed.as_posix()}' (3.0): update '{key}'")
        values[key] = directory.resolve()
    if debug_override is not None:
        values['debug'] = debug_override
    return Config(**values), path, warnings


def validate_paths(config, config_file, require_inputs=True):
    output = Path(config.site_directory).resolve()
    inputs = [('source_directory', config.source_directory)]
    inputs += [(f'targets: {name}: theme', spec['theme']) for name, spec in (config.targets or {}).items()] \
        or [('theme', config.theme)]
    for key, directory in inputs:
        directory = Path(directory).resolve()
        if output == directory or output in directory.parents or directory in output.parents:
            raise ConfigError(f"Unsafe 'site_directory': output and '{key}' must not overlap ({output}, {directory})")
        if require_inputs and not directory.is_dir():
            raise ConfigError(f"'{key}' directory not found: {directory}")
    protected = [config_file.resolve(), GENERATOR_DIRECTORY.resolve()]
    if config.cache_video_directory:
        protected.append(Path(config.cache_video_directory).resolve())
    for path in protected:
        if output == path or output in path.parents:
            raise ConfigError(f"Unsafe 'site_directory': deleting '{output}' would remove '{path}'")
    if output.exists() and not output.is_dir():
        raise ConfigError(f"'site_directory' is not a directory: {output}")
