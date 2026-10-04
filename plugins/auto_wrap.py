import json

from lib.source_scan import leading_settings
from lib.structure import built_pages, template_path

# The title is written as a Jinja string literal (JSON escapes: quotes, backslashes).
# The {% set %} and {% import %} lines at the top of the page (with blank lines
# and comments) come before {% extends %}, so that the theme sees them too:
# {% set layout = 'side' %} chooses the layout.
template_auto_wrap = '''
{{% set pageTitle = {title} %}}
{{% set tocTitle = {title} %}}
{settings}
{{% extends "theme/template/base.html" %}}

{{% block content %}}

{content}

{{% endblock %}}
'''


def pre_process(meta):
    for entry in built_pages(meta):
        file_path = template_path(meta, entry)

        with open(file_path, 'r') as fid:
            file_content = fid.read()

        # Do not change files that are already wrapped
        if '{% block content %}' not in file_content:
            settings = leading_settings(file_content)
            content = template_auto_wrap.format(title=json.dumps(str(entry['title']), ensure_ascii=False),
                                                settings=settings, content=file_content[len(settings):])
            with open(file_path, 'w') as fid:
                fid.write(content)
