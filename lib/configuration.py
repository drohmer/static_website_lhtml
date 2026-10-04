"""User configuration, validation, and the legacy plugin context adapter."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import copy
import difflib
import yaml

GENERATOR_DIRECTORY = Path(__file__).resolve().parents[1]
RENAMED_DIRECTORIES = {'theme_templates': 'themes', 'src_site_example': 'example'}


class ConfigError(ValueError):
    """An actionable configuration error, displayed without a traceback."""


@dataclass(frozen=True)
class Config:
    source_directory: str = 'src_site/'
    site_directory: str = '.site/'
    theme: str = str(GENERATOR_DIRECTORY / 'themes/webpage-frame')
    plugin: list[str] = field(default_factory=lambda: ['plugins/menu.py', 'plugins/redirection_first_page.py'])
    debug: bool = False
    level_print: int = 0
    title_id: bool = True
    keywords: dict = field(default_factory=dict)
    use_tidy: bool = False
    include_head: list[str] = field(default_factory=list)
    plugin_arg: dict = field(default_factory=dict)
    cache_video_directory: str | None = None
    design: dict | str | None = None
    deck: list | dict | str | None = None
    # Legacy extensions stay available to custom plugins, with a warning.
    extras: dict = field(default_factory=dict)

    def to_meta(self):
        values = asdict(self)
        values.update(values.pop('extras'))
        if values['cache_video_directory'] is None:
            del values['cache_video_directory']
        for key in ('design', 'deck'):
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
        # Plugins keep a real, mutable dict, but never mutate the configuration.
        self.meta = self.config.to_meta()
        self.meta.update(config_file=str(self.config_file),
                         config_directory=str(self.config_file.parent) + '/',
                         lib_directory=str(GENERATOR_DIRECTORY) + '/',
                         path_config='', args=self.args, log=self.log,
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


def load_config(filename, debug_override=None):
    path = Path(filename).expanduser().resolve()
    warnings = []
    if not path.exists() and path.name == 'configure_default.yaml':
        replacement = path.with_name('configure_example.yaml')
        if replacement.is_file():
            warnings.append("'configure_default.yaml' was renamed 'configure_example.yaml'; update your command.")
            path = replacement
    try:
        with path.open() as stream:
            data = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read configuration '{path}': {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict) or any(not isinstance(k, str) for k in data):
        raise ConfigError('Configuration must contain named key: value pairs')

    if 'plugin_post' in data:
        warnings.append("'plugin_post' is deprecated; use 'plugin' (all hooks are executed).")
        if 'plugin' in data:
            raise ConfigError("Use only 'plugin', not both 'plugin' and 'plugin_post'")
        data['plugin'] = data.pop('plugin_post')

    defaults = Config().to_meta()
    known = set(defaults) | {'cache_video_directory', 'design', 'deck'}
    reserved = {'args', 'log', 'plugin_paths', 'config_file', 'config_directory',
                'lib_directory', 'current_directory', 'published_site_directory', 'extras',
                'only', 'structure', 'built', 'previous_pages', 'macros'}
    extras = {}
    for key in set(data) - known:
        if key in reserved:
            raise ConfigError(f"'{key}' is runtime state and cannot be set in YAML")
        suggestion = difflib.get_close_matches(key, sorted(known), n=1)
        hint = f" Did you mean '{suggestion[0]}'?" if suggestion else ''
        warnings.append(f"Unknown configuration key '{key}'.{hint} Retained for custom plugins.")
        extras[key] = data[key]
    values = {**defaults, **{k: v for k, v in data.items() if k in known}}
    for key in ('debug', 'title_id', 'use_tidy'):
        if type(values[key]) is not bool:
            raise ConfigError(f"'{key}' must be a boolean (true or false)")
    if type(values['level_print']) is not int or values['level_print'] < 0:
        raise ConfigError("'level_print' must be a non-negative integer")
    for key in ('keywords', 'plugin_arg'):
        if not isinstance(values[key], dict) or any(not isinstance(k, str) for k in values[key]):
            raise ConfigError(f"'{key}' must be a mapping with string keys")
    if 'params' in values['keywords']:
        raise ConfigError("'keywords': 'params' is reserved (Jinja variable of the deck parameters of a page)")
    plugins = values['plugin']
    if isinstance(plugins, str):
        plugins = [plugins]
    elif plugins is None:
        plugins = []
    values['plugin'] = plugins
    for key in ('plugin', 'include_head'):
        if not isinstance(values[key], list) or any(not isinstance(v, str) or not v.strip() for v in values[key]):
            raise ConfigError(f"'{key}' must be a list of non-empty strings")

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
        if key in ('source_directory', 'theme') and not directory.is_dir():
            renamed = Path(*[RENAMED_DIRECTORIES.get(part, part) for part in directory.parts])
            if renamed.is_dir():
                warnings.append(f"'{directory}' was renamed; using '{renamed}'. Update '{key}'.")
                directory = renamed
        values[key] = str(directory.resolve()) + '/'
    if debug_override is not None:
        values['debug'] = debug_override
    return Config(**values, extras=copy.deepcopy(extras)), path, warnings


def validate_paths(config, config_file, require_inputs=True):
    output = Path(config.site_directory).resolve()
    for key in ('source_directory', 'theme'):
        directory = Path(getattr(config, key)).resolve()
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


def layout_output_directory(meta):
    """Validate the layout output before any build or plugin deletion."""
    options = meta.get('plugin_arg', {}).get('layout_report') or {}
    if not isinstance(options, dict):
        raise ConfigError("'plugin_arg.layout_report' must be a mapping")
    value = options.get('output', '.layout/')
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("'plugin_arg.layout_report.output' must be a non-empty path")
    output = (Path(meta['config_directory']) / Path(value).expanduser()).resolve()
    for key in ('source_directory', 'theme', 'site_directory', 'published_site_directory', 'cache_video_directory'):
        if not meta.get(key):
            continue
        path = Path(meta[key]).resolve()
        if path == output or path in output.parents or output in path.parents:
            raise ConfigError(f"Unsafe layout output '{output}': overlaps '{key}' ({path})")
    protected = [GENERATOR_DIRECTORY, Path(meta['config_file']),
                 Path(meta['config_directory']) / 'code',
                 Path(meta['config_directory']) / 'cache_video_directory']
    protected += [Path(path) for path in meta.get('plugin_paths', [])]
    for path in protected:
        path = path.resolve()
        if path == output or output in path.parents:
            raise ConfigError(f"Unsafe layout output '{output}': would remove '{path}'")
    if output.exists() and not output.is_dir():
        raise ConfigError(f'Layout output is not a directory: {output}')
    return output
