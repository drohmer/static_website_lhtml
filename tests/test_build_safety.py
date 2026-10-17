import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch
import pytest
import yaml

from lib.build_output import staged_site
from lib.configuration import ConfigError
from lib.development import snapshot
from lib.layout import build as layout_build, measure
from lib.layout_options import output_directory

REPO = Path(__file__).resolve().parents[1]


def project(tmp_path, **overrides):
    source = tmp_path / 'src'
    source.mkdir(exist_ok=True)
    (source / 'index.html.j2').write_text("{% set pageTitle = 'Home' %}\n<h1>Original</h1>")
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': [], **overrides}))
    return config, source


def build(config, *args):
    return subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), *args],
                          capture_output=True, text=True)


def test_failed_full_and_only_build_preserve_last_site(tmp_path):
    config, source = project(tmp_path)
    assert build(config).returncode == 0
    output = tmp_path / '.site/index.html'
    old = output.read_bytes()
    (source / 'index.html.j2').write_text('{% invalid %}')
    for flags in ((), ('--only', 'index.html')):
        result = build(config, *flags)
        assert result.returncode == 1
        assert output.read_bytes() == old
        assert not list(tmp_path.glob('.site-build-*'))
    (source / 'index.html.j2').write_text('<h1>Replacement</h1>')
    assert build(config).returncode == 0
    assert 'Replacement' in output.read_text()
    assert not list(tmp_path.glob('.site-backup-*'))


def test_failed_plugin_preserves_previous_site(tmp_path):
    config, _ = project(tmp_path)
    assert build(config).returncode == 0
    old = (tmp_path / '.site/index.html').read_bytes()
    (tmp_path / 'broken.py').write_text('def post_process(meta):\n    raise ValueError("broken")\n')
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': ['broken.py']}))
    assert build(config).returncode == 1
    assert (tmp_path / '.site/index.html').read_bytes() == old


def test_publish_failure_rolls_back(tmp_path):
    target = tmp_path / '.site'
    target.mkdir()
    (target / 'keep').write_text('old')
    meta = {'site_directory': str(target), 'debug': False, 'log': Mock()}
    rename = Path.rename
    def failing_rename(self, destination):
        if self.name.startswith('.site-build-'):
            raise OSError('simulated publish failure')
        return rename(self, destination)
    with patch.object(Path, 'rename', failing_rename), pytest.raises(OSError):
        with staged_site(meta):
            (Path(meta['site_directory']) / 'new').write_text('new')
    assert (target / 'keep').read_text() == 'old'
    assert not (target / 'new').exists()


def test_a_target_that_does_not_publish_its_site_leaves_the_previous_one(tmp_path):
    """The PDF export renders HTML as an intermediate and publishes
    slides.pdf instead. It says so (publish_site) rather than deleting the
    directory other stages may still be reading: the staging site is
    dropped at publication, and what was published before is untouched."""
    target = tmp_path / '.site'
    target.mkdir()
    (target / 'keep').write_text('old')
    meta = {'site_directory': str(target), 'debug': False, 'log': Mock()}
    with staged_site(meta):
        staging = Path(meta['site_directory'])
        (staging / 'intermediate.html').write_text('html')
        meta['publish_site'] = False
    assert not staging.exists()
    assert (target / 'keep').read_text() == 'old'
    assert not (target / 'intermediate.html').exists()


def test_a_project_without_the_analysis_is_not_held_to_its_configuration(tmp_path):
    """--check-config answers for the build it would run. A project that
    neither asks for the layout analysis nor configures it must not be
    refused for where its report would have gone: here the sources are the
    configuration directory, so the default .layout/ sits inside them - a
    real error for --layout, and none for a build that never measures."""
    project = tmp_path / 'project'                   # the sources are the project itself
    project.mkdir()
    (project / 'index.html.j2').write_text("{% set pageTitle = 'A' %}\n<h1>A</h1>")
    config = project / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': '.', 'plugin': [],
                                      'site_directory': str(tmp_path / 'out')}))
    assert build(config, '--check-config').returncode == 0
    assert build(config, '--clean', '--layout').returncode == 0      # removes the site, not the reports
    refused = build(config, '--layout')
    assert refused.returncode == 1 and 'Unsafe layout output' in refused.stdout


def test_layout_rejects_unsafe_outputs_before_deleting(tmp_path):
    config, source = project(tmp_path)
    (tmp_path / 'alias').symlink_to(source, target_is_directory=True)
    for output in ('.', 'src', 'src/report', 'alias', '.site', '.site/report', str(REPO), str(REPO / 'themes')):
        config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': [],
            'layout': {'output': output}}))
        for flag in ('--check-config', '--layout'):
            result = build(config, '--layout', flag)
            assert result.returncode == 1, (output, result.stdout)
            assert 'Unsafe layout output' in result.stdout
            assert (source / 'index.html.j2').exists()


def test_the_layout_analysis_validates_even_when_called_directly(tmp_path):
    config, source = project(tmp_path)
    meta = {'config_file': str(config), 'config_directory': str(tmp_path),
            'source_directory': str(source), 'theme': str(REPO / 'themes'),
            'site_directory': str(tmp_path / '.site'), 'log': Mock(),
            'layout': {'output': 'src'}}
    with pytest.raises(ConfigError):
        layout_build.run(meta)
    assert (source / 'index.html.j2').exists()
    meta['layout']['output'] = 'custom-reports'
    assert output_directory(meta) == tmp_path / 'custom-reports'


def test_layout_reports_browser_errors(tmp_path):
    failed = Mock(stdout=iter(['progress 0 1 a.html\n']), stderr=iter(['Chrome failed\n']), returncode=1)
    with patch.object(measure.subprocess, 'Popen', return_value=failed):
        with pytest.raises(RuntimeError, match='Chrome failed'):
            measure.run_node('layout_measure.js', [])


def test_watcher_detects_add_edit_delete(tmp_path):
    folder = tmp_path / 'src'
    folder.mkdir()
    original = snapshot([folder])
    page = folder / 'a.html.j2'
    page.write_text('hello')
    added = snapshot([folder])
    assert added != original
    page.write_text('updated')
    assert snapshot([folder]) != added
    page.unlink()
    assert snapshot([folder]) == original


def test_a_layout_report_that_cannot_run_leaves_the_build_alone(tmp_path):
    """An analysis reports, or reports that it could not run. A missing
    browser (or here, a missing node) used to raise through the plugin and
    throw away a site that had rendered correctly."""
    config, _ = project(tmp_path)
    without_node = dict(os.environ, PATH='/usr/bin:/bin')
    result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--layout'],
                            capture_output=True, text=True, env=without_node)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Layout report not produced' in result.stdout
    assert (tmp_path / '.site/index.html').is_file()
    assert 'Original' in (tmp_path / '.site/index.html').read_text()


def test_nothing_private_of_the_project_reaches_the_site(tmp_path):
    """Three ways a file of the author used to be published: a hidden file in
    a sub-directory of the sources, a link to the project inside them, and
    `src` named in public_page_keys."""
    source = tmp_path / 'src/a'
    source.mkdir(parents=True)
    (source / 'index.html.j2').write_text("{% set pageTitle = 'A' %}\n<h1>A</h1>")
    (source / '.notes.md').write_text('PRIVATE_NOTE')
    (source / '.private').mkdir()
    (source / '.private/x.txt').write_text('PRIVATE_DIRECTORY')
    (tmp_path / 'deck.yaml').write_text(yaml.safe_dump(
        {'slides': ['a'], 'title': 'T'}))
    os.symlink(tmp_path, source / 'project_link', target_is_directory=True)           # the project, from the sources
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'deck': 'deck.yaml'}))

    assert build(config).returncode == 0
    site = tmp_path / '.site'
    published = [p for p in site.rglob('*') if p.is_file()]
    assert published, 'the site is empty'
    for path in published:
        assert not any(part.startswith('.') for part in path.relative_to(site).parts), path
    text = '\n'.join(p.read_text(encoding='utf-8', errors='replace') for p in published)
    assert 'PRIVATE_NOTE' not in text and 'PRIVATE_DIRECTORY' not in text
    assert not (site / 'a/project_link/configure.yaml').exists()
    assert not (site / 'a/project_link/deck.yaml').exists()
    assert 'src' not in json.loads((site / 'structure/structure.json').read_text())[0]

    config.write_text(yaml.safe_dump({'source_directory': 'src', 'public_page_keys': ['src']}))
    failed = build(config)
    assert failed.returncode == 1 and 'public_page_keys' in failed.stdout


def test_an_option_the_analysis_cannot_read_stops_the_build(tmp_path):
    """A measurement that cannot run is reported and the build goes on; an
    option of the wrong shape is a configuration error and stops it, before
    the build starts (lib/layout_options.py, also used by --check-config)."""
    for bad in ({'design_rules': 42}, {'jobs': 'four'}, {'jobs': 0},
                {'width': 'wide'}, {'root': ''}, {'images': 'yes'}, {'contact_rows': -1}):
        config, _ = project(tmp_path, layout=bad)
        result = build(config, '--layout')
        assert result.returncode == 1, (bad, result.stdout + result.stderr)
        said = ' '.join(result.stdout.split())      # independent of the terminal width
        assert 'layout' in said and list(bad)[0] in said, (bad, said)
        assert 'built' not in said, (bad, said)                        # refused before the build
        assert not (tmp_path / '.layout').exists(), bad


def test_a_page_that_places_itself_is_not_wrapped_again(tmp_path):
    """auto_wrap is in the default plugins: a page that already extends the
    theme, or that is a whole document, must be left alone - wrapping the
    first stops the build on two {% extends %}, the second gives two <html>."""
    source = tmp_path / 'src'
    (source / 'own').mkdir(parents=True)
    (source / 'raw').mkdir()
    (source / 'own/index.html.j2').write_text(
        '{% extends "theme/template/base.html" %}\n'
        '{% block head %}<meta name="x">{% endblock %}\n')       # no block content
    (source / 'raw/index.html.j2').write_text('<!DOCTYPE html>\n<html><body><h1>Raw</h1></body></html>\n')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src',
                                      'theme': str(REPO / 'themes/slides')}))
    result = build(config)
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ('own', 'raw'):
        assert (tmp_path / '.site' / name / 'index.html').read_text().upper().count('<!DOCTYPE') == 1


def test_an_option_the_analysis_does_not_know_is_reported(tmp_path):
    """A key of 'layout' that no option matches is a typo: it was read,
    copied and never used, without a word."""
    config, _ = project(tmp_path, layout={'widht': 3000, 'expct': 'x'})
    said = ' '.join(build(config, '--layout').stdout.split())
    assert 'unknown: expct, widht' in said, said



def site_fingerprint(site):
    """Every file of a site with its content: two builds are compared by
    what they publish, not by how they got there."""
    return {str(path.relative_to(site).as_posix()): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(site.rglob('*')) if path.is_file()}


def test_a_partial_build_gives_the_same_site_as_a_full_one(tmp_path):
    """The guarantee of --only: for everything it touches and everything that
    depends on it, a partial build publishes what a full build publishes.
    When the generator cannot tell what depends on what, it widens the build
    and says so (lib/dependencies.py)."""
    source = tmp_path / 'src'
    for name in ('a', 'b', 'c'):
        (source / name).mkdir(parents=True)
        (source / name / 'index.html.j2').write_text(f'= Page {name}\n* first\n')
    theme = tmp_path / 'theme'
    shutil.copytree(REPO / 'themes/slides', theme)
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'site_directory': 'site',
                                      'theme': str(theme)}))
    site = tmp_path / 'site'

    def published(*arguments):
        """The site after a build, as {path: content}."""
        result = build(config, *arguments)
        assert result.returncode == 0, result.stdout + result.stderr
        return site_fingerprint(site), ' '.join(result.stdout.split())

    def from_scratch():
        shutil.rmtree(site, ignore_errors=True)
        return published()[0]

    def edit_page(name, text):
        (source / name / 'index.html.j2').write_text(text)

    def edit_theme(rule):
        (theme / 'css/main.css').write_text((theme / 'css/main.css').read_text() + rule)

    before = from_scratch()
    assert len(before) > 3

    # A page of the project changed: --only on it publishes what a full build does.
    edit_page('b', '= Page b\n* first\n* second, added\n')
    expected = from_scratch()
    assert expected != before, 'the edit changes the site'
    shutil.rmtree(site, ignore_errors=True)
    edit_page('b', '= Page b\n* first\n')          # the site of the first state
    published()
    edit_page('b', '= Page b\n* first\n* second, added\n')
    partial, _ = published('--only', 'b')
    assert partial == expected, 'a partial build must publish what a full build publishes'

    # A shared input changed (the theme): --only cannot tell which pages
    # depend on it, so it widens the build and says so.
    css = theme / 'css/main.css'
    original, rule = css.read_text(), '\n.added { color: red; }\n'
    shutil.rmtree(site, ignore_errors=True)
    published()                                     # a site built with the theme as it is
    css.write_text(original + rule)
    expected = from_scratch()                       # what a full build gives after the edit

    css.write_text(original)                        # back to the first state, site included
    shutil.rmtree(site, ignore_errors=True)
    published()
    css.write_text(original + rule)
    widened, said = published('--only', 'a', '-v')
    assert 'full build' in said, said
    assert widened == expected, 'a widened build must publish what a full build publishes'
