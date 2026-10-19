"""Regression checks: python3 -m unittest discover -s tests -v."""
import os
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from lhtml_site.logger import Logger
from lhtml_site import pdf_export

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
            'theme': str(REPO / 'src/lhtml_site/themes/webpage-frame'),
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
        self.assertEqual(structure[1]['title'], 'Second')       # the new page was read by this build
        self.assertNotIn('custom', structure[1])                # its settings stay out of the site
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
        config['plugin'] = []
        self.config.write_text(yaml.safe_dump(config))
        self.build()
        script = self.site / 'theme/js/menu.js'
        menu = json.loads(script.read_text().split('const toc = ', 1)[1].split(';', 1)[0])
        self.assertEqual([entry['title'] for entry in menu],
                         ["Angles d'Euler (x/y/z)", 'L\'informatique "graphique"'])
        page = (self.site / 'a/index.html').read_text()
        self.assertRegex(page, r"<title>\s*Angles d(&#39;|')Euler \(x/y/z\)\s*</title>")

    @unittest.skipUnless(shutil.which('node'), 'needs Node.js')
    def test_menu_escapes_metadata_and_retains_flags(self):
        self.page('a/index.html.j2', 'First')
        title = 'Le mode "debug"\nC:\\docs'
        (self.source / 'a/config.yaml').write_text(yaml.safe_dump({
            'title': title, 'hide-toc': True, 'level-toc': 2, 'expandable-toc': True}))
        self.build()
        script = self.site / 'theme/js/menu.js'
        result = subprocess.run(['node', '--check', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        encoded = script.read_text().split('const toc = ', 1)[1].split(';', 1)[0]
        menu = json.loads(encoded)
        self.assertEqual(menu[0]['title'], title)
        self.assertEqual(menu[0]['hide-toc'], 'True')
        self.assertEqual(menu[0]['level-toc'], '2')
        self.assertEqual(menu[0]['expandable-toc'], 'True')        # a group the menu folds (cgp)

    @unittest.skipUnless(shutil.which('node'), 'needs Node.js')
    def test_the_page_content_column_reads_the_headings_of_the_page(self):
        """webpage-frame lists the level-2 headings with an id of its content,
        read in the page: no request (it failed from file://), and no
        title_id.json written into the site."""
        config = yaml.safe_load(self.config.read_text())
        config['plugin'] = []
        self.config.write_text(yaml.safe_dump(config))
        self.page('a.html.j2', 'A')
        with (self.source / 'a.html.j2').open('a') as stream:
            stream.write('\n== Alpha\n')
        self.build()
        self.assertEqual(sorted(p.name for p in self.site.rglob('*title_id*.json')), [])
        self.assertIn('id="alpha_l2"', (self.site / 'a.html').read_text())
        script = self.site / 'theme/js/title_id.js'
        self.assertNotIn('fetch', script.read_text())
        harness = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
function element() {
  return {children: [], classList: {add() {}}, style: {}, innerHTML: '',
          appendChild(child) { this.children.push(child); }};
}
for (const [headings, expected] of [
    [[{id: 'alpha_l2', textContent: ' Alpha\n beta '}, {id: 'empty_l2', textContent: ' '}],
     [['#alpha_l2', 'Alpha beta']]],
    [[], []]]) {
  const column = element();
  let selector = null;
  const content = {querySelectorAll: (s) => { selector = s; return headings; }};
  vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
    console,
    document: {querySelector: (s) => s === '#title_id' ? column : s === '#main-content-centered' ? content : null,
               body: content, createElement: element},
    fetch: () => { throw new Error('no request'); }
  });
  assert.strictEqual(selector, 'h2[id]');
  const links = column.children.map((div) => [div.children[0].href, div.children[0].textContent]);
  assert.deepStrictEqual(links, expected);
  assert.strictEqual(column.style.display, expected.length ? 'block' : undefined);
}
"""
        result = subprocess.run(['node', '-e', harness, str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.environ.get('LHTML_BROWSER_TEST') == '1', 'Set LHTML_BROWSER_TEST=1 for Chromium')
    def test_the_page_content_column_in_a_browser(self):
        """The column of webpage-frame, over http and from the file opened on
        disk (3.0 fetched a JSON file: the column was empty from file://)."""
        import functools
        import http.server
        import threading
        from playwright.sync_api import sync_playwright
        (self.source / 'a').mkdir()
        (self.source / 'a/index.html.j2').write_text(
            "{% set n = 'Two' %}\n= Page\n\n== One **bold**\n\nText\n\n=== Deeper\n\n== {{ n }}\n\n"
            "==(#mine) Written\n\n==(.only-class) No id\n")
        (self.source / 'b').mkdir()
        (self.source / 'b/index.html.j2').write_text("= Alone\n\nText\n")
        self.build()

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(self.site)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        column = """() => { const e = document.querySelector('#title_id');
            return [getComputedStyle(e).display,
                    Array.from(e.querySelectorAll('a')).map(a => [a.getAttribute('href'), a.textContent])]; }"""
        expected = ['block', [['#one_**bold**_l2', 'One bold'], ['#two_l2', 'Two'], ['#mine', 'Written']]]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            requests = []
            page.on('request', lambda request: requests.append(request.url))
            for base in (f'http://127.0.0.1:{server.server_address[1]}/', self.site.as_uri() + '/'):
                with self.subTest(base=base):
                    page.goto(base + 'a/index.html')
                    page.wait_for_function("document.querySelector('#title_id').style.display === 'block'")
                    self.assertEqual(page.evaluate(column), expected)
                    page.goto(base + 'b/index.html')
                    page.wait_for_load_state('load')
                    self.assertEqual(page.evaluate(column), ['none', []])
            browser.close()
            self.assertFalse([url for url in requests if url.endswith('.json')], requests)

    def test_a_markdown_heading_from_jinja_gets_its_id_from_its_rendered_text(self):
        (self.source / 'm').mkdir()
        (self.source / 'm/index.md.j2').write_text(
            "# Notes\n\n{% set topic = 'Quaternions *unit*' %}\n## {{ topic }}\n\n## Quaternions unit\n")
        self.build()
        page = (self.site / 'm/index.html').read_text()
        self.assertIn('id="notes_l1"', page)
        self.assertIn('id="quaternions_unit_l2"', page)          # written as text: as in 3.0
        self.assertIn('id="quaternions_unit_id2_l2"', page)      # from Jinja: unique in its page
        self.assertNotIn('{{', page)

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
        from lhtml_site.filesystem import find_files_in_hierarchy
        self.page('nested/index.html.j2', 'First')
        (self.source / 'nested/loop').symlink_to(self.source, target_is_directory=True)
        entries = find_files_in_hierarchy(str(self.source), lambda name: name.endswith('.html.j2'))
        self.assertEqual(entries, [('nested/', 'index.html.j2')])

    @patch.dict(os.environ, {'LHTML_PDF_ENGINE': 'node'})     # the Node export: its commands mocked
    def test_pdf_failures_preserve_html_and_previous_export(self):
        for failing_command in ('node', 'pdftoppm', 'magick', 'pdfunite'):
            with self.subTest(command=failing_command):
                self.site.mkdir(exist_ok=True)
                (self.site / 'index.html').write_text('<h1>Keep me</h1>')
                old_pdf = self.root / 'slides.pdf'
                old_pdf.write_bytes(b'previous PDF')
                attempts = []
                def run(command, check=False, **options):
                    if command[0] == failing_command:
                        attempts.append(command[0])
                        if not check:           # node: tried again, then the export fails
                            return subprocess.CompletedProcess(command, 1, '', 'TimeoutError')
                        raise subprocess.CalledProcessError(1, command)
                    if command[0] == 'node':
                        Path(command[-1].removeprefix('--output=')).write_bytes(b'page')
                    elif command[0] == 'magick':
                        Path(command[-1]).write_bytes(b'image')
                    return subprocess.CompletedProcess(command, 0)
                meta = {'site_directory': str(self.site), 'debug': False, 'log': Logger(),
                        'structure': [{'dir': '', 'filename': 'index.html'}]}
                with patch.object(pdf_export.subprocess, 'run', side_effect=run):
                    with self.assertRaises(RuntimeError if failing_command == 'node'
                                           else subprocess.CalledProcessError) as raised:
                        pdf_export.export(meta)
                if failing_command == 'node':
                    self.assertIn('not made after 3 attempts: TimeoutError', str(raised.exception))
                    self.assertEqual(attempts, [failing_command] * pdf_export.ATTEMPTS)
                self.assertTrue((self.site / 'index.html').exists())
                self.assertEqual(old_pdf.read_bytes(), b'previous PDF')

    @patch.dict(os.environ, {'LHTML_PDF_ENGINE': 'node'})     # the Node export: its commands mocked
    def test_a_pdf_page_that_misses_its_timeout_is_tried_again(self):
        self.site.mkdir()
        calls = []
        def run(command, check=False, **options):
            if command[0] == 'node':
                calls.append(command)
                if len(calls) == 1:                     # Chrome missed its timeout once
                    return subprocess.CompletedProcess(command, 1, '', 'TimeoutError')
                Path(command[-1].removeprefix('--output=')).write_bytes(b'page')
            elif command[0] in ('magick', 'pdfunite'):
                Path(command[-1]).write_bytes(b'export')
            return subprocess.CompletedProcess(command, 0)
        meta = {'site_directory': str(self.site), 'debug': False, 'log': Logger(),
                'structure': [{'dir': '', 'filename': 'index.html'}]}
        with patch.object(pdf_export.subprocess, 'run', side_effect=run):
            pdf_export.export(meta)
        self.assertEqual(len(calls), 2)
        self.assertEqual((self.root / 'slides.pdf').read_bytes(), b'export')

    @patch.dict(os.environ, {'LHTML_PDF_ENGINE': 'node'})     # the Node export: its commands mocked
    def test_pdf_asks_not_to_publish_instead_of_deleting(self):
        self.site.mkdir()
        def run(command, check=False, **options):
            self.assertTrue(self.site.exists())
            if command[0] == 'node':
                Path(command[-1].removeprefix('--output=')).write_bytes(b'page')
            elif command[0] in ('magick', 'pdfunite'):
                Path(command[-1]).write_bytes(b'export')
            return subprocess.CompletedProcess(command, 0)
        meta = {'site_directory': str(self.site), 'debug': False, 'log': Logger(),
                'structure': [{'dir': '', 'filename': 'index.html'}]}
        with patch.object(pdf_export.subprocess, 'run', side_effect=run):
            partial = {**meta, 'only': True}                        # --only: built in the site itself
            pdf_export.export(partial)
            self.assertTrue(self.site.exists())
            self.assertNotIn('publish_site', partial)
            pdf_export.export(meta)
        # The site it rendered was an intermediate of the export: the export
        # says so, and the publication step drops it (lhtml_site/build_output.py).
        # It does not delete a directory other stages may still be reading.
        self.assertTrue(self.site.exists())
        self.assertFalse(meta['publish_site'])
        self.assertEqual((self.root / 'slides.pdf').read_bytes(), b'export')
        self.assertEqual((self.root / 'images/slide_000.jpg').read_bytes(), b'export')


if __name__ == '__main__':
    unittest.main()
