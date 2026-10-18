"""A page says what it is at its top, in YAML, without writing Jinja.

    ---
    layout: stack
    ---
    = Title

LHTML read and removed this form until 3.0; the build reads it now
(lhtml_site/front_matter.py) and removes it before LHTML. Before it, a page setting was either
a Jinja statement in the page ({% set layout = 'stack' %}) or a config.yaml
sitting next to it - a file per directory, for a setting of one page.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

REPO = Path(__file__).resolve().parents[1]


class FrontMatterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml-front-matter-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / 'src').mkdir()

    def write(self, name, text, **config):
        page = self.root / 'src' / name
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(text)
        if config:
            (page.parent / 'config.yaml').write_text(yaml.safe_dump(config))

    def build(self, deck=None, ok=True, **options):
        settings = {'source_directory': 'src', 'site_directory': 'out',
                    'theme': str(REPO / 'themes/slides'), **options}
        if deck is not None:
            (self.root / 'deck.yaml').write_text(yaml.safe_dump(deck))
            settings['deck'] = 'deck.yaml'
        config = self.root / 'configure.yaml'
        config.write_text(yaml.safe_dump(settings))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return ' '.join(result.stdout.split())

    def body(self, name='a/index.html'):
        html = (self.root / 'out' / name).read_text()
        return re.search(r'<body[^>]*>', html).group(0), html

    def test_after_a_byte_order_mark(self):
        (self.root / 'src/a').mkdir()
        (self.root / 'src/a/index.html.j2').write_bytes('\ufeff---\nlayout: stack\n---\n= Titre\n'.encode())
        self.build()
        body, html = self.body()
        self.assertIn('layout-stack', body)
        self.assertNotIn('layout: stack', html)

    def test_malformed_yaml_fails_naming_the_page(self):
        self.write('a/index.html.j2', '---\nlayout: [stack\n---\n= Titre\n')
        output = self.build(ok=False)
        # the console of rich may cut a long path (step C of docs/design.md)
        self.assertIn('a/index.html.j2', output.replace(' ', ''))
        self.assertIn('invalid YAML front matter', output)

    def test_not_shown_in_a_build_for_development(self):
        from lhtml_site import front_matter, source_map, source_scan
        page = '---\nlayout: stack\n---\n= Titre\n'
        marked = source_map.add_markers(page, 's', source_scan.value_tags())
        self.assertEqual(front_matter.split(marked)[1], {'layout': 'stack'})

    def test_an_lhtml_error_names_the_source_not_the_build_directory(self):
        self.write('a/index.html.j2', '= Titre\nnote ::# old comment\n')
        output = self.build(ok=False)
        self.assertIn('src/a/index.html.j2:2:6:error:::#commentswereremoved', output.replace(' ', ''))
        self.assertNotIn('.site-build-', output)

    def test_line_breaks_of_the_configuration_reach_lhtml(self):
        self.write('a/index.html.j2', '= Titre\n\nline one\nline two\n')
        self.build(**{'line-breaks': True})
        self.assertIn('line one<br>', self.body()[1])

    def test_a_page_chooses_its_layout_without_a_jinja_statement(self):
        self.write('a/index.html.j2', '---\nlayout: stack\n---\n= Titre\n\n* un\n')
        self.build()
        body, html = self.body()
        self.assertIn('layout-stack', body)
        self.assertNotIn('---', html)               # the settings are not printed
        self.assertIn('<h1', html)

    def test_the_two_forms_agree(self):
        """The Jinja statement still works, and says the same thing."""
        self.write('a/index.html.j2', '---\nlayout: stack\n---\n= Titre\n\n* un\n')
        self.write('b/index.html.j2', "{% set layout = 'stack' %}\n= Titre\n\n* un\n")
        self.build()
        self.assertEqual(self.body('a/index.html')[0], self.body('b/index.html')[0])

    def test_the_directory_then_the_page_then_the_deck(self):
        """From the least specific to the most: the config.yaml of the
        directory, the front matter of the page, then the deck entry."""
        self.write('a/index.html.j2', '---\nlayout: stack\n---\n= Titre\n', layout='side')
        self.build()
        self.assertIn('layout-stack', self.body()[0])    # the page over its directory

        self.build(deck={'slides': [{'path': 'a', 'title': 'T', 'layout': 'side'}]})
        self.assertIn('layout-side', self.body()[0])     # the deck over the page

    def test_a_page_that_places_itself_keeps_its_front_matter_out_of_the_page(self):
        """A page with its own {% extends %} is not wrapped by the build;
        its settings must still be read, and still not be printed."""
        self.write('a/index.html.j2',
                   "---\nlayout: stack\n---\n{% extends 'theme/template/base.html' %}\n"
                   '{% block content %}\n= Titre\n{% endblock %}\n')
        self.build()
        body, html = self.body()
        self.assertIn('layout-stack', body)
        self.assertNotIn('layout: stack', html)

    def test_text_that_only_looks_like_a_front_matter_is_left_alone(self):
        """Three dashes in the middle of a page are content, not settings."""
        self.write('a/index.html.j2', '= Titre\n\ntexte\n\n---\nlayout: stack\n---\n')
        self.build()
        body, html = self.body()
        self.assertNotIn('layout-stack', body)
        self.assertIn('layout: stack', html)


if __name__ == '__main__':
    unittest.main()
