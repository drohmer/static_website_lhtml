import argparse
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
    with patch.object(layout_report.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'Chrome failed')):
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
