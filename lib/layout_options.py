"""Options of the layout analysis, and their validation.

They live here, and not in the module that reads them, so that
`--check-config` answers for what the build will refuse, and refuses it
before the build rather than after it.
"""
from pathlib import Path

from lib.configuration import GENERATOR_DIRECTORY, ConfigError

# The fallback of a theme that declares nothing (lib/theme.py). A theme
# says what its content is and what size a page has; a project says what it
# wants measured and how. Engine, then theme, then project.
DEFAULTS = {'root': 'body', 'exclude': 'nav, footer', 'width': 1920, 'height': 1080, 'images': 'render',
            'threshold': 4, 'output': '.layout/', 'max_words': 80, 'min_font': 20,
            'contact_columns': 4, 'contact_rows': 4, 'jobs': 'auto'}

# An option that is not in DEFAULTS: the rules of the design checks.
OTHER_OPTIONS = {'design_rules': dict}

TEXT_OPTIONS = ('root', 'exclude', 'output')
COUNT_OPTIONS = ('width', 'height', 'threshold', 'max_words', 'min_font',
                 'contact_columns', 'contact_rows')

MAX_JOBS = 6            # 'auto': half the processors, at most this many


def jobs(options):
    """Pages measured at the same time: `jobs` of the configuration, or
    'auto' (half of the processors, at most MAX_JOBS)."""
    import os
    value = options.get('jobs', 'auto')
    if value in (None, 'auto'):
        return max(1, min(MAX_JOBS, (os.cpu_count() or 2) // 2))
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"layout: jobs must be 'auto' or a positive integer, not {value!r}")
    return value


def options_of(meta):
    """The options of the report: the defaults, then what the theme declares
    (lib/theme.py), then what the configuration gives. The design rules are
    validated by lib/design_checks.py."""
    from lib.design_checks import validate as validate_design_rules
    from lib.theme import of as theme_manifest
    options = dict(DEFAULTS)
    if meta.get('theme'):
        options.update(theme_manifest(meta)['layout'])
    options.update(meta.get('layout') or {})
    options['chrome'] = meta.get('chrome')      # its own configuration key
    try:
        validate_design_rules(options.get('design_rules', {}))
    except ValueError as error:
        raise ConfigError(str(error)) from None
    return options


def validate(meta, log=None):
    """Check the options before the build. A value the report cannot make
    sense of stops the build (ConfigError, naming the key); a key it does
    not know is a typo, reported as a warning - it would otherwise be read,
    copied and never used."""
    given = meta.get('layout') or {}
    if not isinstance(given, dict):
        raise ConfigError("'layout' must be a mapping")
    unknown = sorted(set(given) - set(DEFAULTS) - set(OTHER_OPTIONS))
    if unknown and log is not None:
        log.warning(f"layout: option(s) ignored, unknown: {', '.join(unknown)}")
    options = options_of(meta)
    jobs(options)
    for key in TEXT_OPTIONS:
        if not isinstance(options[key], str) or not options[key].strip():
            raise ConfigError(f"layout: '{key}' must be a non-empty string, not {options[key]!r}")
    for key in COUNT_OPTIONS:
        if isinstance(options[key], bool) or not isinstance(options[key], int) or options[key] <= 0:
            raise ConfigError(f"layout: '{key}' must be a positive integer, not {options[key]!r}")
    if not (isinstance(options['images'], bool) or options['images'] == 'render'):
        raise ConfigError(f"layout: 'images' must be true, 'render' or false, not {options['images']!r}")
    for key, kind in OTHER_OPTIONS.items():
        if key in given and not isinstance(given[key], kind):
            raise ConfigError(f"layout: '{key}' must be a mapping, not {given[key]!r}")
    return options


def output_directory(meta):
    """Validate the layout output before any build or deletion."""
    options = meta.get('layout') or {}
    if not isinstance(options, dict):
        raise ConfigError("'layout' must be a mapping")
    value = options.get('output', DEFAULTS['output'])
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("'layout.output' must be a non-empty path")
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
    return output / (meta.get('build_scope') or '')     # one report per deck and target
