"""The page placed in the template of its theme.

A core stage, not a plugin: a source written in LHTML is a fragment, and
without this it reaches the site as a bare fragment. It runs after the
extensions of the pre stage, because an extension writes content and the
theme wraps what the content ends up being - which is what used to be a
rule about the order of two plugins (tests/test_plugin_order.py).
"""
import json
import re

from lib.source_scan import leading_settings
from lib.structure import built_pages, template_path
from lib.theme import of as theme_manifest

# The title is written as a Jinja string literal (JSON escapes: quotes, backslashes).
# The {% set %} and {% import %} lines at the top of the page (with blank lines
# and comments) come before {% extends %}, so that the theme sees them too:
# {% set layout = 'side' %} chooses the layout.
# The template and the block are the theme's, declared in its theme.yaml
# (lib/theme.py): this plugin wraps a page, it does not decide in what.
template_auto_wrap = '''
{{% set pageTitle = {title} %}}
{{% set tocTitle = {title} %}}
{settings}
{{% extends "{template}" %}}

{{% block {block} %}}

{content}

{{% endblock %}}
'''


# A page the theme must not wrap again: it places itself in the theme
# ({% extends %}, with or without a {% block content %}) or it is a whole
# document of its own. Wrapping the first gives two {% extends %}, which
# stops the build on a message naming neither the page nor the plugin;
# wrapping the second gives a page with two <html>, silently.
WRAPPED = re.compile(r'{%-?\s*(?:block\s+content|extends)\b')
DOCUMENT = re.compile(r'\A\s*(?:<!doctype\b|<html\b)', re.IGNORECASE)


def strip_front_matter(text):
    """The source without the YAML settings at its top, if it has any."""
    from lhtml import process_yaml
    try:
        return process_yaml(text)[0]
    except Exception:               # malformed YAML: not a front matter
        return text


def wrapped(text):
    """Whether a source already places itself: the theme leaves it alone."""
    return bool(WRAPPED.search(text) or DOCUMENT.match(text))


def run(meta):
    manifest = theme_manifest(meta)
    for entry in built_pages(meta):
        file_path = template_path(meta, entry)

        with open(file_path, 'r', encoding='utf-8') as fid:
            file_content = fid.read()

        if not wrapped(file_content):
            # The front matter is read as the settings of the page
            # (lib/pages.py) and removed here: once the page is placed in
            # the template, it is no longer at the top of the document, and
            # LHTML only removes one that is.
            file_content = strip_front_matter(file_content)
            settings = leading_settings(file_content)
            # The title of a page is one line: it goes in <title> and in the
            # menu. A deck entry may hold several (lib/deck.py keeps the
            # first one when it scaffolds the page); keep the same one here,
            # or the rest of it is printed in the tab of the browser.
            title = str(entry['title']).strip().splitlines()
            content = template_auto_wrap.format(title=json.dumps(title[0] if title else '', ensure_ascii=False),
                                                settings=settings, content=file_content[len(settings):],
                                                template=manifest['template'], block=manifest['content_block'])
            with open(file_path, 'w', encoding='utf-8') as fid:
                fid.write(content)
