"""A page is measured again only when something it shows changed
(lhtml_site/layout/build.py, _reusable), and a contact sheet is taken again only
when it shows something else (lhtml_site/layout/measure.py)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import pytest
import yaml

from lhtml_site import dependencies
from lhtml_site.layout import build, measure

REPO = Path(__file__).resolve().parents[1]
OPTIONS = {'width': 1920, 'height': 1080, 'root': 'body', 'exclude': 'nav, footer', 'images': 'render',
           'chrome': None}


class Reusable(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.site, self.out = root / 'site', root / 'out'
        (self.site / 'css').mkdir(parents=True)
        self.out.mkdir()
        (self.site / 'a.html').write_text('<h1>A</h1>')
        (self.site / 'css/s.css').write_text('h1 {}')
        (root / 'a.html.j2').write_text('= A')
        self.meta = {'site_directory': str(self.site), 'config_directory': str(root)}
        self.page = {'name': 'a.html', 'out': str(self.out), 'source': str(root / 'a.html.j2')}
        self.key = build._measure_key(OPTIONS)
        self.write()

    def write(self, **changes):
        layout = {'measure': self.key, 'source': 'a.html.j2', 'render_health': {'status': 'ready'},
                  'dependencies': {'artifacts': {name: dependencies.file_hash(self.site / name)
                                                 for name in ('a.html', 'css/s.css')}}}
        layout.update(changes)
        (self.out / 'layout.json').write_text(json.dumps(layout))
        (self.out / 'render.png').write_bytes(b'png')

    def reusable(self, key=None):
        return build._reusable(self.meta, self.page, key or self.key, {})

    def test_a_page_nothing_changed_is_kept(self):
        self.assertTrue(self.reusable())

    def test_a_changed_html_or_resource_is_measured_again(self):
        (self.site / 'css/s.css').write_text('h1 { color: red }')
        self.assertFalse(self.reusable())
        self.write()
        (self.site / 'a.html').write_text('<h1>B</h1>')
        self.assertFalse(self.reusable())

    def test_other_options_another_script_or_missing_images(self):
        self.assertFalse(self.reusable({**self.key, 'width': 1280}))
        self.assertFalse(self.reusable({**self.key, 'script': 'other'}))
        self.assertFalse(self.reusable({**self.key, 'images': True}))       # no overlay.png
        os.remove(self.out / 'render.png')
        self.assertFalse(self.reusable())

    def test_an_incomplete_or_external_or_older_report_is_measured_again(self):
        self.write(render_health={'status': 'incomplete'})
        self.assertFalse(self.reusable())
        self.write(dependencies={'artifacts': {'a.html': dependencies.file_hash(self.site / 'a.html')},
                                 'external_resources': ['https://x.org/a.js']})
        self.assertFalse(self.reusable())
        self.write(measure=None)                # measured before reports said how
        self.assertFalse(self.reusable())
        self.write(source='b.html.j2')
        self.assertFalse(self.reusable())


class ContactSheets(unittest.TestCase):

    def test_a_sheet_showing_the_same_pictures_is_not_taken_again(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            (out / 'pages/a').mkdir(parents=True)
            (out / 'pages/a/render.png').write_bytes(b'png')
            rows = [('a.html', 'pages/a', {'findings': []})]
            options = {'contact_columns': 4, 'contact_rows': 4, 'chrome': None}
            taken = []

            def run(sheets, chrome, log):
                taken.append(len(sheets))
                for sheet in sheets:
                    Path(sheet['png']).write_bytes(b'png')
            with mock.patch.object(measure, 'screenshot_sheets', run):
                measure.write_contact_sheets(str(out), rows, {'w': 1920, 'h': 1080}, options, None)
                measure.write_contact_sheets(str(out), rows, {'w': 1920, 'h': 1080}, options, None)
                time.sleep(0.01)
                (out / 'pages/a/render.png').write_bytes(b'new')    # the page measured again
                measure.write_contact_sheets(str(out), rows, {'w': 1920, 'h': 1080}, options, None)
            self.assertEqual(taken, [1, 1])


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_a_second_layout_measures_only_what_changed(tmp_path):
    (tmp_path / 'src').mkdir()
    for name in ('a', 'b'):
        (tmp_path / f'src/{name}.html.j2').write_text(f"{{% set pageTitle = '{name}' %}}\n<h1>{name}</h1>")
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': []}))

    def layout():
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--layout'],
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        return ' '.join(result.stdout.split())
    assert 'Layout report: 2 measured' in layout()
    assert 'Layout report: 0 measured, 2 unchanged' in layout()
    (tmp_path / 'src/b.html.j2').write_text("{% set pageTitle = 'b' %}\n<h1>b, changed</h1>")
    assert 'Layout report: 1 measured, 1 unchanged' in layout()
