"""Pages written in Markdown (index.md.j2, lib/markdown_page.py)."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from lib import credits, deck, markdown_page, pages, source_scan

REPO = Path(__file__).resolve().parents[1]


class ConvertTests(unittest.TestCase):

    def test_mathematics_is_kept_for_mathjax_but_not_in_code(self):
        html = markdown_page.convert('a \\(x_1 * y_2\\) b\n\n\\[a_b\n= c_d\\]\n\n`\\(c_d\\)`\n')
        self.assertIn('a \\(x_1 * y_2\\) b', html)
        self.assertIn('\\[a_b\n= c_d\\]', html)
        self.assertIn('<code>\\(c_d\\)</code>', html)

    def test_a_fenced_block_is_highlighted_as_lhtml_does(self):
        html = markdown_page.convert('```python\nx = "\\(y\\)"  # z\n```\n')
        self.assertTrue(html.startswith('<div class="code"><pre>'))
        self.assertIn('\\(y\\)', html)

    def test_the_id_of_a_heading_and_its_plain_text(self):
        self.assertEqual(markdown_page.convert('## A *b* {: #a_b_l2}\n'), '<h2 id="a_b_l2">A <em>b</em></h2>\n')
        self.assertEqual(markdown_page.plain('A *b* `c` &amp; [d](e)'), 'A b c & d')

    def test_tables_and_raw_html(self):
        html = markdown_page.convert('| a |\n|---|\n| 1 |\n\n<div class="x">y</div>\n')
        self.assertIn('<td>1</td>', html)
        self.assertIn('<div class="x">y</div>', html)


class NamesTests(unittest.TestCase):

    def test_the_file_names_the_markup(self):
        self.assertEqual([pages.markup(n) for n in ('index.html.j2', 'index.md.j2', 'index.md', 'a.html')],
                         ['lhtml', 'markdown', None, None])
        self.assertEqual(pages.html_name('extra.md.j2'), 'extra.html')
        self.assertEqual(pages.template_name('extra.html', 'markdown'), 'extra.md.j2')

    def test_the_zones_and_images_of_a_markdown_source(self):
        scan = source_scan.Scan('# T\n```\n# no\n![a](no.png)\n```\n![b](assets/y.png "t")\n', 'markdown')
        self.assertEqual([z.kind for z in scan.zones], ['code'])
        self.assertEqual(credits.files_used(scan), ['assets/y.png'])


class BuildTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml markdown ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.site = self.root / 'site'

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def build(self, *args, theme='slides'):
        self.write('c.yaml', yaml.safe_dump({'source_directory': 'src', 'site_directory': 'site', 'theme': theme}))
        return subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', 'c.yaml', *args],
                              cwd=self.root, capture_output=True, text=True)

    def test_a_markdown_page_in_the_theme_next_to_an_lhtml_one(self):
        self.write('src/a/index.md.j2', "---\nlayout: stack\n---\n{% set n = 2 %}\n# Hello *world*\n\n"
                                        "{{ n }} items, div::x and \\(a_b\\).\n\n```\n# not a title\n```\n\n"
                                        "## Again\n")
        self.write('src/b/index.html.j2', '= B\n\n{{ linkTo_hello_world }}\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        html = (self.site / 'a/index.html').read_text()
        self.assertIn('<body class="layout-stack">', html)
        self.assertIn('<title> Hello world </title>', html)
        self.assertIn('<h1 id="hello_world_l1">Hello <em>world</em></h1>', html)
        self.assertIn('<p>2 items, div::x and \\(a_b\\).</p>', html)        # LHTML does not read it
        self.assertIn('<h2 id="again_l2">Again</h2>', html)
        self.assertNotIn('not_a_title', html)
        self.assertIn('href="../a/index.html"', (self.site / 'b/index.html').read_text())

    def test_a_markdown_page_does_not_place_itself_and_an_error_is_at_its_line(self):
        self.write('src/a/index.md.j2', "{% extends 'theme/template/base.html' %}\n# A\n")
        result = self.build()
        self.assertEqual(result.returncode, 1)
        self.assertIn('a Markdown page is placed in the theme by the build', ' '.join(result.stdout.split()))
        self.write('src/a/index.md.j2', '# A\n\ntext\n\n{{ missing.x }}\n')
        result = self.build()
        self.assertIn("src/a/index.md.j2:5: error: Jinja: 'missing' is undefined", result.stdout)

    def test_scaffold_writes_the_markup_of_the_name(self):
        created = deck.scaffold([deck.Entry(pointer='a/extra.md.j2', meta={'title': 'New'})], self.root)
        self.assertEqual((self.root / 'a/extra.md.j2').read_text(), '# New\n')
        self.assertEqual(len(created), 1)
        self.assertEqual(deck.scaffold([deck.Entry(pointer='a/extra.html', meta={'title': 'N'})], self.root), [])


if __name__ == '__main__':
    unittest.main()
