import importlib.util
import os
import subprocess
import sys

import lhtml
from jinja2 import Environment, FileSystemLoader

from lib.tracking import TrackingLoader, lhtml_includes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_templates_read_by_jinja_are_recorded(tmp_path):
    (tmp_path / 'macros.j2').write_text('{% macro m() %}M{% endmacro %}')
    (tmp_path / 'page.j2').write_text('{% import "macros.j2" as k %}{{ k.m() }}')
    loader = TrackingLoader(FileSystemLoader(tmp_path), None, [tmp_path])
    assert Environment(loader=loader).get_template('page.j2').render() == 'M'
    assert loader.used == {str((tmp_path / 'page.j2').resolve()), str((tmp_path / 'macros.j2').resolve())}


def test_lhtml_includes_are_recorded_and_the_reader_restored(tmp_path):
    part = tmp_path / 'part.lhtml'
    part.write_text('* Included item\n')
    from lhtml import process
    original = process.read_source
    used = set()
    with lhtml_includes(None, used):
        html = lhtml.run('include::part.lhtml\n', {'directory_include': [str(tmp_path)]})
    assert 'Included item' in html
    assert str(part.resolve()) in used
    assert process.read_source is original


def test_the_layout_report_does_not_load_the_agent_extension():
    code = ("import importlib.util, sys; sys.path.insert(0, %r); import generate; "
            "spec = importlib.util.spec_from_file_location('r', %r); "
            "spec.loader.exec_module(importlib.util.module_from_spec(spec)); "
            "print(any(n == 'agent' or n.startswith('agent.') for n in sys.modules))"
            % (ROOT, os.path.join(ROOT, 'plugins', 'layout_report.py')))
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=ROOT)
    assert result.stdout.strip() == 'False', result.stdout + result.stderr
