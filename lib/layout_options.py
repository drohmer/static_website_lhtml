"""Options of the layout report, and their validation.

They live here, and not in the plugin that reads them, so that the generator
can check a configuration without loading any plugin: `--check-config`
answers for what the build will refuse, and it refuses it before the build
rather than after it.
"""
from lib.configuration import ConfigError

DEFAULTS = {'root': 'body', 'exclude': 'nav, footer', 'width': 1920, 'height': 1080, 'images': True,
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
        raise ConfigError(f"layout_report: jobs must be 'auto' or a positive integer, not {value!r}")
    return value


def options_of(meta):
    """The options of the report: the defaults, then what the configuration
    gives. The design rules are validated by lib/design_checks.py."""
    from lib.design_checks import validate as validate_design_rules
    options = dict(DEFAULTS)
    options.update((meta.get('plugin_arg') or {}).get('layout_report') or {})
    options['chrome'] = meta.get('chrome')      # configuration key, not a plugin_arg
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
    given = (meta.get('plugin_arg') or {}).get('layout_report') or {}
    if not isinstance(given, dict):
        raise ConfigError("'plugin_arg.layout_report' must be a mapping")
    unknown = sorted(set(given) - set(DEFAULTS) - set(OTHER_OPTIONS))
    if unknown and log is not None:
        log.warning(f"layout_report: option(s) ignored, unknown: {', '.join(unknown)}")
    options = options_of(meta)
    jobs(options)
    for key in TEXT_OPTIONS:
        if not isinstance(options[key], str) or not options[key].strip():
            raise ConfigError(f"layout_report: '{key}' must be a non-empty string, not {options[key]!r}")
    for key in COUNT_OPTIONS:
        if isinstance(options[key], bool) or not isinstance(options[key], int) or options[key] <= 0:
            raise ConfigError(f"layout_report: '{key}' must be a positive integer, not {options[key]!r}")
    if not isinstance(options['images'], bool):
        raise ConfigError(f"layout_report: 'images' must be a boolean, not {options['images']!r}")
    for key, kind in OTHER_OPTIONS.items():
        if key in given and not isinstance(given[key], kind):
            raise ConfigError(f"layout_report: '{key}' must be a mapping, not {given[key]!r}")
    return options
