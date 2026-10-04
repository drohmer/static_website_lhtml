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


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_nested_fixed_element_lines_and_changes(tmp_path):
    source = tmp_path / 'src/s'
    source.mkdir(parents=True)
    page = source / 'index.html.j2'
    page.write_text("= Title\n\ndiv::[font-size:85%;]\nA line of text that runs under the box\n"
                    "::[position:fixed; top:60px; left:100px; width:300px; height:80px; "
                    "background-color:rgb(200,0,0);] ::\n::\n")
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': [],
                                      'theme': str(REPO / 'themes/slides')}))
    run = lambda: subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--layout'],
                                 capture_output=True, text=True, timeout=90)
    assert run().returncode == 0
    report = (tmp_path / '.layout/pages/s/index.html/layout.md').read_text()
    assert '| 1 | 1 | title |' in report                     # line of the source (data-src)
    assert 'in #2 |' in report                              # the fixed box, measured on its own
    assert 'HIDDEN TEXT #2 under #3' in report or 'COLLISION #2 × #3' in report
    page.write_text(page.read_text().replace('top:60px', 'top:550px'))
    assert run().returncode == 0
    changes = (tmp_path / '.layout/changes.md').read_text()
    assert '1 changed' in changes and 'moved by (+0, +490) px' in changes
