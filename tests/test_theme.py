"""The contract a theme declares in theme.yaml (lib/theme.py)."""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from lib import theme
from lib.configuration import ConfigError
from lib.layout_options import options_of

REPO = Path(__file__).resolve().parents[1]


def write(directory, **manifest):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / theme.MANIFEST).write_text(yaml.safe_dump(manifest), encoding='utf-8')
    return directory


def test_a_theme_with_no_manifest_builds_as_before(tmp_path):
    bare = tmp_path / 'bare'
    bare.mkdir()
    assert theme.read(bare) == theme.DEFAULTS
    assert options_of({'theme': str(bare)})['root'] == 'body'


def test_the_themes_shipped_declare_what_the_engine_used_to_assume():
    """The slides answers were the defaults of the engine for all three
    themes; each theme now says its own."""
    assert theme.read(REPO / 'themes/slides')['layout']['root'] == 'body'
    assert theme.read(REPO / 'themes/webpage-frame')['layout']['root'] == '#main-content-centered'
    for name in ('slides', 'slides-pdf', 'webpage-frame'):
        assert theme.path(REPO / 'themes' / name).is_file()


def test_engine_then_theme_then_project(tmp_path):
    """The project keeps the last word: it is the one that knows it added
    a banner to the pages of its theme."""
    custom = write(tmp_path / 'custom', layout={'root': '#content', 'width': 1000})
    assert options_of({'theme': str(custom)})['root'] == '#content'
    assert options_of({'theme': str(custom)})['width'] == 1000
    assert options_of({'theme': str(custom)})['height'] == 1080          # the engine's
    assert options_of({'theme': str(custom)})['threshold'] == 4          # not a theme's to set
    over = options_of({'theme': str(custom), 'layout': {'root': 'main'}})
    assert over['root'] == 'main' and over['width'] == 1000


def test_a_manifest_the_build_cannot_read_is_refused(tmp_path):
    for manifest, message in (({'templates': 'x'}, 'unknown theme setting'),
                              ({'template': ''}, 'must be a non-empty string'),
                              ({'layout': {'threshold': 2}}, 'a theme does not set threshold'),
                              ({'layout': 'body'}, 'layout must be a mapping')):
        directory = write(tmp_path / 'bad', **manifest)
        with pytest.raises(ConfigError) as error:
            theme.read(directory)
        assert message in str(error.value)


def test_the_page_is_wrapped_in_the_template_the_theme_declares(tmp_path):
    """auto_wrap used to write 'theme/template/base.html' and 'content'
    itself: a plugin that wraps a page should not decide in what."""
    source = tmp_path / 'src'
    source.mkdir()
    (source / 'index.html.j2').write_text('= Titre\n\ntexte\n')
    custom = write(tmp_path / 'custom', template='theme/template/page.html', content_block='body')
    (custom / 'template').mkdir()
    (custom / 'template/page.html').write_text(
        '<html><body><main>{% block body %}{% endblock %}</main></body></html>')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'theme': str(custom),
                                      'plugin': [str(REPO / 'plugins/auto_wrap.py')]}))
    result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config)],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    page = (tmp_path / '.site/index.html').read_text()
    assert '<main>' in page and '<h1 id="titre_l1">Titre</h1>' in page
