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


def wrapped(text):
    """Whether a source already places itself: the theme leaves it alone."""
    return bool(WRAPPED.search(text) or DOCUMENT.match(text))


def pre_process(meta):
    manifest = theme_manifest(meta)
    for entry in built_pages(meta):
        file_path = template_path(meta, entry)

        with open(file_path, 'r', encoding='utf-8') as fid:
            file_content = fid.read()

        if not wrapped(file_content):
            settings = leading_settings(file_content)
            content = template_auto_wrap.format(title=json.dumps(str(entry['title']), ensure_ascii=False),
                                                settings=settings, content=file_content[len(settings):],
                                                template=manifest['template'], block=manifest['content_block'])
            with open(file_path, 'w', encoding='utf-8') as fid:
                fid.write(content)
