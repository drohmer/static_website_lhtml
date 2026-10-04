"""Layouts of the pages (design.yaml, section layouts), the Jinja variable
`page`, and the design lint (lib/lint.py)."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from lib import design, lint
from lib.configuration import ConfigError, load_config

REPO = Path(__file__).resolve().parents[1]
SLIDES = design.load_design(REPO / 'themes/slides')


class LayoutDesignTests(unittest.TestCase):

    def test_slides_layouts(self):
        self.assertEqual(sorted(SLIDES['layouts']), ['section', 'side', 'stack'])
        self.assertIn('/* layout side */', design.design_css(SLIDES))
        reference = design.design_markdown(SLIDES)
        self.assertIn('## Layouts', reference)
        self.assertIn("{% set layout = 'name' %}", reference)

    def test_invalid_layouts(self):
        for layouts in ({'side': 'x'}, {'side': {'css': '', 'width': 1}}, {'a b': {}}):
            with self.assertRaises(design.DesignError):
                design.load_design(REPO / 'themes/slides', {'layouts': layouts})
        self.assertNotIn('side', design.load_design(REPO / 'themes/slides', {'layouts': {'side': None}})['layouts'])


class LayoutBuildTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml layouts ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.site = self.root / 'site'

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def build(self, deck=None, *args):
        config = {'source_directory': 'src', 'site_directory': 'site', 'theme': str(REPO / 'themes/slides'),
                  'plugin': ['plugins/auto_wrap.py']}
        if deck is not None:
            config['deck'] = deck
        self.write('config.yaml', yaml.safe_dump(config))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(self.root / 'config.yaml'),
                                 *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return ' '.join((result.stdout + result.stderr).split())

    def body(self, name):
        html = (self.site / name / 'index.html').read_text()
        return html[html.index('<body'):].split('>', 1)[0] + '>'

    def test_layout_from_the_page_its_configuration_and_the_deck(self):
        self.write('src/a/index.html.j2', "{% set layout = 'side' %}\n{% set n = params.n | default(2) %}\n"
                                          "= A\n{{ n }} items\nmedia::\nimg::x.png\n::\n")
        self.write('src/b/index.html.j2', '= B\n')
        self.write('src/b/config.yaml', 'layout: stack\n')
        self.write('src/c/index.html.j2', '= C {{ page.message }}\n')
        output = self.build([{'path': 'a'}, 'b', {'path': 'c', 'layout': 'side-s', 'message': 'hello'}])
        self.assertEqual(self.body('a'), '<body class="layout-side">')
        self.assertIn('2 items', (self.site / 'a/index.html').read_text())
        self.assertEqual(self.body('b'), '<body class="layout-stack">')
        self.assertEqual(self.body('c'), '<body class="layout-side layout-side-s">')
        self.assertIn('C hello', (self.site / 'c/index.html').read_text())
        self.assertIn('Lint: 2 value(s) written by hand in 2 of 3', output)    # b, c: a layout without media::

    def test_lint_option(self):
        self.write('src/a/index.html.j2', '= A\ndiv::[height:50px;]::\n::[position:fixed; top:100px;] x ::\n')
        self.write('src/b/index.html.j2', '= B\ngap::\n')
        output = self.build(None, '--lint')
        self.assertIn('src/a/index.html.j2:2: spacer: div::[height:50px;]:: -> gap::l', output)
        self.assertIn('src/a/index.html.j2:3: position: position:fixed; top:100px', output)
        self.assertIn('Lint: 2 value(s) written by hand in 1 of 2 page(s)', output)
        self.assertFalse(self.site.exists())                         # no generation
        output = self.build(None, '--lint', '--only', 'b')
        self.assertIn('no value written by hand in 1 page(s)', output)

    def test_page_and_params_are_reserved_keywords(self):
        self.write('src/a/index.html.j2', '= A\n')
        for name in ('page', 'params'):
            self.write('config.yaml', yaml.safe_dump({'source_directory': 'src', 'keywords': {name: 1}}))
            with self.assertRaises(ConfigError):
                load_config(self.root / 'config.yaml')


class LintTests(unittest.TestCase):
    linter = lint.Linter(SLIDES)

    def kinds(self, text, layout=None):
        return [(f.line, f.kind, f.advice) for f in self.linter.lint(text, layout)]

    def test_values_and_their_replacement(self):
        text = ('= T\n'
                'div::[height:25px;]::\n'
                '::[height:75px]::\n'
                '::[font-size:85%; line-height:1.3em;] x ::\n'
                'div::[font-size:72%] y ::\n'
                'span::[color:gray] z ::\n'
                'div::[text-align:center;] w ::\n'
                'div::[display:flex; justify-content:space-around;] v ::\n'
                'div::[margin-top:100px;] u ::\n'
                '<div style="position:absolute; left:10px">t</div>\n')
        found = self.kinds(text)
        self.assertEqual([k for _, k, _ in found],
                         ['spacer', 'spacer', 'font-size', 'font-size', 'color', 'align', 'flex', 'offset', 'position'])
        self.assertEqual(found[0][2], 'gap::')
        self.assertEqual(found[1][2], 'gap::xl')
        self.assertTrue(found[2][2].startswith('small::'))
        self.assertTrue(found[3][2].startswith('tiny::'))

    def test_code_blocks_are_not_linted(self):
        self.assertEqual(self.kinds('code::[css]\ndiv::[height:25px;]::\n::\ncode::[css] a ::\n'), [])

    def test_layouts(self):
        self.assertEqual(self.kinds("{% set layout = 'grid' %}\n= T\n")[0][1], 'layout')
        self.assertIn('media::', self.kinds('= T\n', layout='stack')[0][2])
        self.assertEqual(self.kinds("{% set layout = 'side-l' %}\n= T\nmedia::\nimg::a.png\n::\n"), [])
        self.assertEqual(self.kinds("{% set layout = 'side' %}\nmedia::\n::\naside::\n::\n")[0][2], 'media::')


if __name__ == '__main__':
    unittest.main()
