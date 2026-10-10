"""Regression checks: python3 -m unittest discover -s tests -v."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from lib.logger import Logger
from plugins import generate_pdf

REPO = Path(__file__).resolve().parents[1]


class GeneratorRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lhtml review ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'src'
        self.source.mkdir()
        self.site = self.root / 'site'
        self.config = self.root / 'config.yaml'
        self.config.write_text(yaml.safe_dump({
            'source_directory': str(self.source),
            'site_directory': str(self.site),
            'theme': str(REPO / 'themes/webpage-frame'),
        }))

    def page(self, name, title):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{% set pageTitle = '" + title + "' %}\n<h1>" + title + '</h1>')

    def build(self, *args):
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'),
                                 '-i', str(self.config), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_absolute_and_relative_paths(self):
        self.page('a/index.html.j2', 'First')
        self.build()
        self.assertTrue((self.site / 'a/index.html').exists())
        config = yaml.safe_load(self.config.read_text())
        for key in ('source_directory', 'site_directory', 'theme'):
            config[key] = os.path.relpath(config[key], self.root)
        self.config.write_text(yaml.safe_dump(config))
        self.build()
        self.assertTrue((self.site / 'a/index.html').exists())

    def test_root_homepage_is_preserved(self):
        self.page('index.html.j2', 'Actual homepage')
        self.build()
        self.assertIn('<h1>Actual homepage</h1>', (self.site / 'index.html').read_text())
        self.build('--only', 'index.html')
        self.assertIn('<h1>Actual homepage</h1>', (self.site / 'index.html').read_text())

    def test_plain_homepage_is_preserved(self):
        (self.source / 'index.html').write_text('<h1>Static homepage</h1>')
        self.page('a/index.html.j2', 'First')
        self.build()
        self.assertEqual((self.site / 'index.html').read_text(), '<h1>Static homepage</h1>')

    def test_only_after_add_rename_remove_is_a_full_build(self):
        self.page('a/index.html.j2', 'First')
        (self.source / 'asset.txt').write_text('original asset')
        self.build('-d')
        (self.source / 'asset.txt').write_text('changed asset')
        self.page('b/index.html.j2', 'Second')
        (self.source / 'b/config.yaml').write_text('custom: fresh\n')
        self.build('--only', 'a')
        menu = (self.site / 'theme/js/menu.js').read_text()
        self.assertIn('b/index.html', menu)
        self.assertTrue((self.site / 'sitemap/second.html').exists())
        structure = yaml.safe_load((self.site / 'structure/structure.yaml').read_text())
        self.assertEqual(structure[1]['custom'], 'fresh')
        self.assertEqual((self.site / 'asset.txt').read_text(), 'changed asset')
        (self.source / 'a/index.html.j2').unlink()
        self.page('b/index.html.j2', 'Renamed')
        self.build('--only', 'b')
        self.assertFalse((self.site / 'a/index.html').exists())
        self.assertFalse((self.site / 'sitemap/second.html').exists())
        self.assertTrue((self.site / 'sitemap/renamed.html').exists())
        menu = (self.site / 'theme/js/menu.js').read_text()
        self.assertNotIn('a/index.html', menu)
        self.assertIn('Renamed', menu)
        self.assertIn('b/index.html', (self.site / 'index.html').read_text())

    def test_empty_page_configuration(self):
        self.page('a/index.html.j2', 'First')
        metadata = self.source / 'a/config.yaml'
        for text in ('', '# Optional metadata\n'):
            metadata.write_text(text)
            self.build()
            self.build('--only', 'a')
            self.assertTrue((self.site / 'a/index.html').is_file())

    def test_titles_keep_apostrophes_and_parentheses(self):
        (self.source / 'a').mkdir()
        (self.source / 'a/index.html.j2').write_text("= Angles d'Euler (x/y/z)\n\nText\n")
        (self.source / 'b').mkdir()
        (self.source / 'b/index.html.j2').write_text(
            "{% set pageTitle = 'L\\'informatique \"graphique\"' %}\n<h1>B</h1>")
        config = yaml.safe_load(self.config.read_text())
        config['plugin'] = ['plugins/auto_wrap.py', 'plugins/menu.py']
        self.config.write_text(yaml.safe_dump(config))
        self.build()
        script = self.site / 'theme/js/menu.js'
        menu = json.loads(script.read_text().split('const toc = ', 1)[1].split(';', 1)[0])
        self.assertEqual([entry['title'] for entry in menu],
                         ["Angles d'Euler (x/y/z)", 'L\'informatique "graphique"'])
        page = (self.site / 'a/index.html').read_text()
        self.assertRegex(page, r"<title>\s*Angles d(&#39;|')Euler \(x/y/z\)\s*</title>")

    def test_menu_escapes_metadata_and_retains_flags(self):
        self.page('a/index.html.j2', 'First')
        title = 'Le mode "debug"\nC:\\docs'
        (self.source / 'a/config.yaml').write_text(yaml.safe_dump({
            'title': title, 'hide-toc': True, 'level-toc': 2}))
        self.build()
        script = self.site / 'theme/js/menu.js'
        result = subprocess.run(['node', '--check', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        encoded = script.read_text().split('const toc = ', 1)[1].split(';', 1)[0]
        menu = json.loads(encoded)
        self.assertEqual(menu[0]['title'], title)
        self.assertEqual(menu[0]['hide-toc'], 'True')
        self.assertEqual(menu[0]['level-toc'], '2')

    def test_each_page_has_its_own_heading_summary(self):
        config = yaml.safe_load(self.config.read_text())
        config['plugin'] = ['plugins/title_submenu.py']
        self.config.write_text(yaml.safe_dump(config))
        self.page('a.html.j2', 'A')
        self.page('b.html.j2', 'B')
        with (self.source / 'a.html.j2').open('a') as stream:
            stream.write('\n== Alpha\n')
        with (self.source / 'b.html.j2').open('a') as stream:
            stream.write('\n== Beta\n')
        self.build()
        for filename, heading in [('a.html', 'Alpha'), ('b.html', 'Beta')]:
            summary = json.loads((self.site / (filename + '.title_id.json')).read_text())
            self.assertEqual([entry['title'] for entry in summary], [heading])
            self.assertIn('id="' + summary[0]['id'] + '"', (self.site / filename).read_text())
        # Emulate an output directory generated with the old JS reader.
        script = self.site / 'theme/js/title_id.js'
        script.write_text('old reader')
        self.build()
        self.assertIn("filename + '.title_id.json'", script.read_text())
        # Exercise the actual reader for named pages, encoded names and index URLs.
        harness = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
for (const [pathname, expected] of [['/a.html', 'a.html.title_id.json'],
                                  ['/b.html', 'b.html.title_id.json'],
                                  ['/a%20b.html', 'a%20b.html.title_id.json'],
                                  ['/folder/', 'index.html.title_id.json']]) {
  const requests = [];
  vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
    window: {location: {pathname}}, console,
    document: {querySelector: () => ({innerHTML: ''})},
    fetch: (path) => {requests.push(path); return Promise.resolve({json: () => []});}
  });
  assert.deepStrictEqual(requests, [expected]);
}
"""
        result = subprocess.run(['node', '-e', harness, str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_deep_pages_are_generated_in_full_and_only_modes(self):
        name = 'a/b/c/d/e/f/g/index.html.j2'
        self.page(name, 'Deep')
        self.build()
        html = self.site / name.removesuffix('.j2')
        self.assertIn('<h1>Deep</h1>', html.read_text())
        self.page(name, 'Updated')
        self.build('--only', 'a/b/c/d/e/f/g')
        self.assertIn('<h1>Updated</h1>', html.read_text())

    def test_directory_walk_avoids_symlink_cycles(self):
        from lib.filesystem import find_files_in_hierarchy
        self.page('nested/index.html.j2', 'First')
        (self.source / 'nested/loop').symlink_to(self.source, target_is_directory=True)
        entries = find_files_in_hierarchy(str(self.source), lambda name: name.endswith('.html.j2'))
        self.assertEqual([e['path'].filepath_local() for e in entries], ['nested/index.html.j2'])
        self.assertEqual(find_files_in_hierarchy(str(self.source), lambda name: True, max_depth=0), [])

    def test_pdf_failures_preserve_html_and_previous_export(self):
        for failing_command in ('node', 'pdftoppm', 'magick', 'pdfunite'):
            with self.subTest(command=failing_command):
                self.site.mkdir(exist_ok=True)
                (self.site / 'index.html').write_text('<h1>Keep me</h1>')
                old_pdf = self.root / 'slides.pdf'
                old_pdf.write_bytes(b'previous PDF')
                def run(command, check):
                    self.assertTrue(check)
                    if command[0] == failing_command:
                        raise subprocess.CalledProcessError(1, command)
                    if command[0] == 'node':
                        Path(command[-1].removeprefix('--output=')).write_bytes(b'page')
                    elif command[0] == 'magick':
                        Path(command[-1]).write_bytes(b'image')
                    return subprocess.CompletedProcess(command, 0)
                meta = {'site_directory': str(self.site), 'debug': False, 'log': Logger(),
                        'structure': [{'dir': '', 'filename': 'index.html'}]}
                with patch.object(generate_pdf.subprocess, 'run', side_effect=run):
                    with self.assertRaises(subprocess.CalledProcessError):
                        generate_pdf.post_process(meta)
                self.assertTrue((self.site / 'index.html').exists())
                self.assertEqual(old_pdf.read_bytes(), b'previous PDF')

    def test_pdf_success_cleans_only_after_publication(self):
        self.site.mkdir()
        def run(command, check):
            self.assertTrue(self.site.exists())
            if command[0] == 'node':
                Path(command[-1].removeprefix('--output=')).write_bytes(b'page')
            elif command[0] in ('magick', 'pdfunite'):
                Path(command[-1]).write_bytes(b'export')
            return subprocess.CompletedProcess(command, 0)
        meta = {'site_directory': str(self.site), 'debug': False, 'log': Logger(),
                'structure': [{'dir': '', 'filename': 'index.html'}]}
        with patch.object(generate_pdf.subprocess, 'run', side_effect=run):
            generate_pdf.post_process({**meta, 'only': True})       # --only: built in the site itself
            self.assertTrue(self.site.exists())
            generate_pdf.post_process(meta)
        self.assertFalse(self.site.exists())
        self.assertEqual((self.root / 'slides.pdf').read_bytes(), b'export')
        self.assertEqual((self.root / 'images/slide_000.jpg').read_bytes(), b'export')


if __name__ == '__main__':
    unittest.main()
