"""Opt-in browser integration test, enabled in CI and for local smoke checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import yaml
import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_two_pages_same_folder_have_distinct_reports(tmp_path):
    source = tmp_path / 'src'
    source.mkdir()
    for name, title in [('a', 'Alpha'), ('b', 'Beta')]:
        (source / (name + '.html.j2')).write_text(
            "{% set pageTitle = '" + title + "' %}\n<h1>" + title + '</h1>')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': []}))
    result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--layout'],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ('a', 'b'):
        folder = tmp_path / '.layout/pages' / (name + '.html')
        assert (folder / 'layout.json').is_file()
        assert (folder / 'render.png').is_file()
        assert (folder / 'layout.md').is_file()
        assert json.loads((folder / 'layout.json').read_text())['source'] == 'src/' + name + '.html.j2'
        assert (tmp_path / '.site' / (name + '.html')).is_file()
    assert (tmp_path / '.layout/contact_01.png').is_file()
    summary = (tmp_path / '.layout/summary.md').read_text()
    assert 'a.html' in summary and 'b.html' in summary
