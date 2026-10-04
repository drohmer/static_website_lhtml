import json
import re

from lib.structure import built_pages, template_path

# The title is written as a Jinja string literal (JSON escapes: quotes, backslashes).
# The {% set %} lines at the top of the page come before {% extends %}, so that
# the theme sees them too: {% set layout = 'side' %} chooses the layout.
template_auto_wrap = '''
{{% set pageTitle = {title} %}}
{{% set tocTitle = {title} %}}
{settings}
{{% extends "theme/template/base.html" %}}

{{% block content %}}

{content}

{{% endblock %}}
'''


# Blank lines, one-line {# comments #} and {% set name = value %} at the top of a page
LEADING_SETTINGS = re.compile(r'(?:[ \t]*(?:\{%-?\s*set\s+[^%\n]*=[^\n]*?-?%\}|\{#[^\n]*?#\})?[ \t]*\n)*')


def pre_process(meta):
    for entry in built_pages(meta):
        file_path = template_path(meta, entry)

        with open(file_path, 'r') as fid:
            file_content = fid.read()

        # Do not change files that are already wrapped
        if '{% block content %}' not in file_content:
            settings = LEADING_SETTINGS.match(file_content).group(0)
            content = template_auto_wrap.format(title=json.dumps(str(entry['title']), ensure_ascii=False),
                                                settings=settings, content=file_content[len(settings):])
            with open(file_path, 'w') as fid:
                fid.write(content)
