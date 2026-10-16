"""The settings a page writes about itself, in YAML at its top:

    ---
    layout: stack
    ---
    = Title

LHTML read this form until 3.0; it now takes its options from its caller
only, so the generator reads it, and removes it before LHTML.
"""
import re

import yaml

# Only at the very beginning of the source (after blank lines at most), so
# that '---' elsewhere is kept.
FRONT_MATTER = re.compile(r'\A\s*---\n(.*?)\n---[ \t]*$', re.DOTALL | re.MULTILINE)


def split(text):
    """(the source without its front matter, the settings): the source as it
    is and {} when it has none, or when its YAML is not a mapping."""
    match = FRONT_MATTER.search(text.replace('\r\n', '\n'))
    if not match:
        return text, {}
    try:
        settings = yaml.safe_load(match.group(1))
    except yaml.YAMLError:          # malformed YAML: not a front matter
        return text, {}
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        return text, {}
    return text.replace('\r\n', '\n')[match.end():], settings
