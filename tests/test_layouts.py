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
        css = design.design_css(SLIDES)
        self.assertIn('anchor(--layout-intro bottom, var(--layout-top))', css)     # intro:: in side
        self.assertIn('.media.here', css)
        self.assertTrue({'intro', 'placeholder', 'large', 'media'} <= set(SLIDES['macros']))

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
        self.assertEqual((self.site / 'structure/agents.md').read_text(),
                         (REPO / 'docs/agents.md').read_text())          # the guide for agents
        from plugins import layout_report
        self.assertIn('`../site/structure/agents.md`',
                      layout_report.summary_markdown([], design='../site/structure/design.md'))
        self.assertIn('Lint: 2 value(s) written by hand in 2 of 3', output)    # b, c: a layout without media::

    def test_layout_after_an_import_or_a_comment(self):
        self.write('src/m.html', '{% macro hello() %}Hello{% endmacro %}')
        self.write('src/a/index.html.j2', "{% import 'm.html' as m %}\n::# a comment\n"
                                          "{% set layout = 'side' %}\n= A\n{{ m.hello() }}\nmedia::\nimg::x.png\n::\n")
        self.build()
        self.assertEqual(self.body('a'), '<body class="layout-side">')
        self.assertIn('Hello', (self.site / 'a/index.html').read_text())

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
        output = self.build(['b'], '--lint', '--only', 'a')         # a page excluded from the deck
        self.assertIn('2 value(s) written by hand in 1 of 1 page(s)', output)

    def test_page_and_params_are_reserved_keywords(self):
        self.write('src/a/index.html.j2', '= A\n')
        for name in ('page', 'params'):
            self.write('config.yaml', yaml.safe_dump({'source_directory': 'src', 'keywords': {name: 1}}))
            with self.assertRaises(ConfigError):
                load_config(self.root / 'config.yaml')

    def test_own_extends_with_a_layout(self):
        self.write('src/a/index.html.j2', "{% extends 'theme/template/base.html' %}\n{% set layout = 'side' %}\n"
                                          "{% block content %}\n= A\nmedia::\nimg::x.png\n::\n{% endblock %}\n")
        self.build()
        self.assertEqual(self.body('a'), '<body class="layout-side">')

    def test_several_tags_on_a_line_at_the_top(self):
        """auto_wrap keeps only the lines holding one {% set %} before {% extends %}."""
        self.write('src/a/index.html.j2', "{% set n = 2 %}{% if n > 1 %}\n= Big\n{% endif %}\n")
        self.build()
        self.assertIn('Big', (self.site / 'a/index.html').read_text())


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

    def test_more_values_and_exceptions(self):
        text = ("{% set layout = 'side' %}\n"
                'aside::[top:400px;]\n'
                '::[font-size:120%] x ::\n'
                '::[line-height:1.5em] y ::\n'
                '::(.x)[display:none] z ::\n'
                'img::a.png[width:500px]\n'
                '<iframe style="width:10px" src=a></iframe>\n'
                '::[font-size:75%] w ::\n'
                'media::\n::\n')
        found = self.kinds(text)
        self.assertEqual([k for _, k, _ in found],
                         ['font-size', 'line-height', 'display', 'size', 'iframe', 'font-size', 'layout'])
        self.assertTrue(found[0][2].startswith('large::'))
        self.assertTrue(found[5][2].startswith('tiny::'))          # a size, not credit:: (gray)

    def test_code_blocks_are_not_linted(self):
        self.assertEqual(self.kinds('code::[css]\ndiv::[height:25px;]::\n::\ncode::[-]\n'
                                    'verbatim::[]\n::[font-size:85%] x ::\nverbatim::[-]\n'
                                    '`::[font-size:85%] x ::` ::# ::[font-size:85%] x ::\n'), [])
        # what follows a code block is linted
        found = self.kinds('code::[python]\nx = 1\ncode::[-]\ndiv::[position:fixed; top:100px]\n::\n')
        self.assertEqual(found[0][:2], (4, 'position'))

    def test_layouts(self):
        self.assertEqual(self.kinds("{% set layout = 'grid' %}\n= T\n")[0][1], 'layout')
        self.assertIn('media::', self.kinds('= T\n', layout='stack')[0][2])
        self.assertEqual(self.kinds("{% set layout = 'side-l' %}\n= T\nmedia::\nimg::a.png\n::\n"), [])
        self.assertEqual(self.kinds("{% set layout = 'side' %}\nmedia::\n::\naside::\n::\n")[0][2], 'media::')

    def test_layout_names_with_a_dash(self):
        linter = lint.Linter({**SLIDES, 'layouts': {**SLIDES['layouts'], 'two-cols': {}}})
        self.assertEqual(linter.lint("{% set layout = 'two-cols' %}\n= T\n"), [])
        self.assertEqual(linter.lint("{% set layout = 'grid-s' %}\n= T\n")[0].kind, 'layout')

    def test_layout_not_at_the_top(self):
        page = "{% import 'm.html' as m %}\n::# a comment\n{% set layout = 'side' %}\nmedia::\n::\n"
        self.assertEqual(self.kinds(page), [])
        found = self.kinds("= T\n{% set layout = 'side' %}\nmedia::\n::\n")
        self.assertEqual(found[0][:2], (2, 'layout'))
        self.assertIn('top of the page', found[0][2])
        # a page with its own {% extends %}: the set outside its blocks applies
        own = "{% extends 'theme/template/base.html' %}\n{% set layout = 'side' %}\n{% block content %}\nmedia::\n::\n"
        self.assertEqual(self.kinds(own + '{% endblock %}\n'), [])
        inside = "{% extends 'b.html' %}\n{% block content %}\n{% set layout = 'side' %}\nmedia::\n::\n{% endblock %}\n"
        self.assertEqual(self.kinds(inside)[0][:2], (3, 'layout'))


if __name__ == '__main__':
    unittest.main()


class ProjectRulesTests(unittest.TestCase):
    """The lint section of a design: small text on list items, patterns."""
    linter = lint.Linter({**SLIDES, 'lint': {
        'small_text': True,
        'rules': {'part-number': {'pattern': r'\bPart \d', 'advice': 'name the topic'}}}})

    def kinds(self, text):
        return [(f.line, f.kind) for f in self.linter.lint(text)]

    def test_small_text_on_list_items(self):
        text = ('= T\n'
                'small::\n'
                '* first\n'
                '* second\n'
                '::\n'
                '* tiny:: a whole item ::\n'
                '* an item with credit:: a caption ::\n'
                'small::\n'
                'A note, not a list\n'
                '::\n'
                'col::\n'
                'tiny:: Caption ::\n'
                '::\n')
        self.assertEqual(self.kinds(text), [(2, 'small-text'), (6, 'small-text')])

    def test_patterns_skip_math_and_code(self):
        text = ('= T\n'
                '* Seen in Part 2\n'
                '* \\(\\text{Part 3}\\)\n'
                'code::[python]\nPart 4\ncode::[-]\n')
        self.assertEqual(self.kinds(text), [(2, 'part-number')])

    def test_off_by_default(self):
        self.assertEqual(lint.Linter(SLIDES).lint('small::\n* item in Part 2\n::\n'), [])

    def test_invalid_rules(self):
        for bad in ({'unknown': 1}, {'small_text': 'yes'}, {'rules': {'a': {'pattern': '('}}},
                    {'rules': {'a': 'text'}}):
            with self.assertRaises(design.DesignError):
                design._check({'lint': bad}, 'test')

    def test_blocks_followed_as_lhtml_reads_them(self):
        cases = {
            'media::\nsmall::\ncaption\n::\ngap::\n::\n* a\n* b\n': [],          # gap:: has no closer
            'small::{data-x=1}\n* item\n::\n': [(1, 'small-text')],
            'small::\n::(.x)\n::\n* item\n::\n': [(1, 'small-text')],          # anonymous block
            'small::\n* a\n::nl\n* b\n::\n': [(1, 'small-text')],             # ::nl is not a closer
            'small::\n  * indented: not a list\n::\n': [],
        }
        for text, expected in cases.items():
            self.assertEqual(self.kinds(text), expected, text)

    def test_patterns_only_in_the_text(self):
        text = ("{# Part 1 #}\n<p title=\"Part 2\">x</p>\n{% set t = 'Part 3' %}\n"
                "img::assets/Part 4.png\n* real Part 5\n")
        self.assertEqual(self.kinds(text), [(5, 'part-number')])

    def test_extending_design_changes_an_advice(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / 'base.yaml'
            base.write_text(yaml.safe_dump({'lint': {'rules': {'r': {'pattern': 'x', 'advice': 'a'}}}}))
            child = Path(folder) / 'child.yaml'
            child.write_text(yaml.safe_dump({'extends': 'base.yaml', 'lint': {'rules': {'r': {'advice': 'b'}}}}))
            loaded = design.load_design(Path(folder) / 'none', child)
            self.assertEqual(loaded['lint']['rules']['r'], {'pattern': 'x', 'advice': 'b'})
            child.write_text(yaml.safe_dump({'lint': {'rules': {'s': {'advice': 'no pattern'}}}}))
            with self.assertRaises(design.DesignError):
                design.load_design(Path(folder) / 'none', child)

