import os

from jinja2 import Environment, FileSystemLoader

from lib.tracking import TrackingLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_templates_read_by_jinja_are_recorded(tmp_path):
    (tmp_path / 'macros.j2').write_text('{% macro m() %}M{% endmacro %}')
    (tmp_path / 'page.j2').write_text('{% import "macros.j2" as k %}{{ k.m() }}')
    loader = TrackingLoader(FileSystemLoader(tmp_path), [tmp_path])
    assert Environment(loader=loader).get_template('page.j2').render() == 'M'
    assert loader.used == {str((tmp_path / 'page.j2').resolve()), str((tmp_path / 'macros.j2').resolve())}
