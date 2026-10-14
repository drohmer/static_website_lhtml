import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch
import pytest
import yaml

from lib.build_output import staged_site
from lib.configuration import layout_output_directory, ConfigError
from lib.development import snapshot
from plugins import layout_report

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


def test_layout_rejects_unsafe_outputs_before_deleting(tmp_path):
    config, source = project(tmp_path)
    (tmp_path / 'alias').symlink_to(source, target_is_directory=True)
    for output in ('.', 'src', 'src/report', 'alias', '.site', '.site/report', str(REPO), str(REPO / 'themes')):
        config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': [],
            'plugin_arg': {'layout_report': {'output': output}}}))
        for flag in ('--check-config', '--layout'):
            result = build(config, '--layout', flag)
            assert result.returncode == 1, (output, result.stdout)
            assert 'Unsafe layout output' in result.stdout
            assert (source / 'index.html.j2').exists()


def test_layout_plugin_validates_even_when_called_directly(tmp_path):
    config, source = project(tmp_path)
    meta = {'config_file': str(config), 'config_directory': str(tmp_path),
            'source_directory': str(source), 'theme': str(REPO / 'themes'),
            'site_directory': str(tmp_path / '.site'), 'log': Mock(),
            'plugin_arg': {'layout_report': {'output': 'src'}}}
    with pytest.raises(ConfigError):
        layout_report.post_process(meta)
    assert (source / 'index.html.j2').exists()
    meta['plugin_arg']['layout_report']['output'] = 'custom-reports'
    assert layout_output_directory(meta) == tmp_path / 'custom-reports'


def test_layout_reports_browser_errors(tmp_path):
    failed = Mock(stdout=iter(['progress 0 1 a.html\n']), stderr=iter(['Chrome failed\n']), returncode=1)
    with patch.object(layout_report.subprocess, 'Popen', return_value=failed):
        with pytest.raises(RuntimeError, match='Chrome failed'):
            layout_report._run_node('layout_measure.js', [])


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
    os.symlink(tmp_path, source / 'project_link')           # the project, from the sources
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
    the analysis writes anything."""
    for bad in ({'design_rules': 42}, {'jobs': 'four'}, {'jobs': 0}):
        config, _ = project(tmp_path, plugin_arg={'layout_report': bad})
        result = build(config, '--layout')
        assert result.returncode == 1, (bad, result.stdout + result.stderr)
        assert 'layout_report' in result.stdout and 'configuration of layout_report.py' in result.stdout
        assert not (tmp_path / '.layout').exists(), bad
