from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import lhtml
import yaml

from lib import design
from lib.configuration import ConfigError, load_config

REPO = Path(__file__).resolve().parents[1]
HAS_MACROS = hasattr(lhtml, 'registry_with_macros')


class DesignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lhtml design ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_merge_overrides_and_removes(self):
        base = {'tokens': {'font': {'small': '85%', 'tiny': '70%'}},
                'macros': {'box': {'class': 'box'}, 'gap': {'class': 'gap'}}}
        merged = design.merge(base, {'tokens': {'font': {'small': '80%'}}, 'macros': {'gap': None}})
        self.assertEqual(merged['tokens']['font'], {'small': '80%', 'tiny': '70%'})
        self.assertEqual(list(merged['macros']), ['box'])
        self.assertEqual(base['tokens']['font']['small'], '85%')

    def test_theme_and_override_file(self):
        theme = self.root / 'theme'
        theme.mkdir()
        (theme / 'design.yaml').write_text('tokens: {space: {m: 25px}}\nmacros: {box: {class: box}}\n')
        override = self.root / 'mine.yaml'
        override.write_text('tokens: {space: {m: 30px}}\n')
        loaded = design.load_design(theme, str(override))
        self.assertEqual(loaded['tokens'], {'space': {'m': '30px'}})
        self.assertEqual(loaded['macros'], {'box': {'class': 'box'}})
        self.assertEqual(design.load_design(self.root / 'none'), {'tokens': {}, 'macros': {}})

    def test_invalid_design(self):
        with self.assertRaises(design.DesignError):
            design.load_design(self.root, {'colors': {}})
        with self.assertRaises(design.DesignError):
            design.flatten_tokens({'font': {'small': ['85%']}})
        with self.assertRaises(design.DesignError):
            design.flatten_tokens({'font size': '1px'})

    def test_css_and_reference(self):
        d = {'tokens': {'font': {'small': '85%'}, 'space': {'m': 25}},
             'macros': {'small': {'class': 'small', 'doc': 'Smaller text.',
                                  'css': '.small { font-size: var(--font-small); }'}}}
        css = design.design_css(d)
        self.assertIn('--font-small: 85%;', css)
        self.assertIn('--space-m: 25;', css)
        self.assertIn('.small { font-size: var(--font-small); }', css)
        reference = design.design_markdown(d)
        self.assertIn('### `small::`', reference)
        self.assertIn('font-size: 85%', reference)

    @unittest.skipUnless(HAS_MACROS, 'requires lhtml-markup >= 2.5')
    def test_bundled_designs_are_valid(self):
        for theme in ('slides', 'slides-pdf'):
            d = design.load_design(REPO / 'themes' / theme)
            self.assertIn('gap', d['macros'])
            design.flatten_tokens(d['tokens'])
            lhtml.registry_with_macros(d['macros'])
            for name in set(re.findall(r'var\(--([\w-]+)\)', design.design_css(d))):
                self.assertIn(name, design.flatten_tokens(d['tokens']), f'{theme}: undefined token --{name}')

    def test_config_design_key(self):
        config = self.root / 'config.yaml'
        config.write_text('design: missing.yaml\n')
        with self.assertRaises(ConfigError):
            load_config(config)
        config.write_text('design: [1]\n')
        with self.assertRaises(ConfigError):
            load_config(config)
        (self.root / 'mine.yaml').write_text('tokens: {}\n')
        config.write_text('design: mine.yaml\n')
        loaded, _, warnings = load_config(config)
        self.assertEqual(loaded.design, str(self.root / 'mine.yaml'))
        self.assertEqual(warnings, [])

    @unittest.skipUnless(HAS_MACROS, 'requires lhtml-markup >= 2.5')
    def test_generation_with_macros(self):
        source = self.root / 'src'
        (source / 'a').mkdir(parents=True)
        (source / 'a/index.html.j2').write_text(
            "{% set pageTitle = 'A' %}\n{% extends 'theme/template/base.html' %}\n"
            "{% block content %}\n= A\naside::[top:300px;] x ::\ngap::l\nnote:: y ::\n{% endblock %}\n")
        site = self.root / 'site'
        config = self.root / 'config.yaml'
        config.write_text(yaml.safe_dump({
            'source_directory': str(source), 'site_directory': str(site),
            'theme': str(REPO / 'themes/slides'), 'plugin': [],
            'design': {'tokens': {'space': {'l': '60px'}},
                       'macros': {'note': {'class': 'note', 'css': '.note { color: red; }'}}},
        }))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        page = (site / 'a/index.html').read_text()
        self.assertIn('<div class="aside" style="top:300px;"> x </div>', page)
        self.assertIn('<div class="gap gap-l"></div>', page)
        self.assertIn('<div class="note"> y </div>', page)
        self.assertIn('theme/css/design.css', page)
        css = (site / 'theme/css/design.css').read_text()
        self.assertIn('--space-l: 60px;', css)
        self.assertIn('.note { color: red; }', css)


if __name__ == '__main__':
    unittest.main()


class DesignRegressionTests(unittest.TestCase):
    def test_macro_spec_must_be_a_mapping(self):
        with self.assertRaisesRegex(design.DesignError, "macro 'foo' must be a mapping"):
            design.load_design(REPO / 'themes/slides', {'macros': {'foo': 'bar'}})

    def test_empty_design_still_writes_css(self):
        with tempfile.TemporaryDirectory() as root:
            d = design.load_design(REPO / 'themes/slides', {'tokens': None, 'macros': None})
            self.assertEqual(d, {'tokens': {}, 'macros': {}})
            path = design.write_design({'site_directory': root}, d)
            self.assertIn(':root {', path.read_text())


class DesignExtendsTests(unittest.TestCase):
    def test_pdf_theme_extends_slides(self):
        self.assertEqual(design.load_design(REPO / 'themes/slides-pdf'), design.load_design(REPO / 'themes/slides'))

    def test_extends_and_loop(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / 'base.yaml').write_text('tokens: {a: 1, b: 2}\n')
            (root / 'mine.yaml').write_text('extends: base.yaml\ntokens: {b: 3}\n')
            self.assertEqual(design.load_design(root / 'none', str(root / 'mine.yaml'))['tokens'], {'a': 1, 'b': 3})
            self.assertEqual(design.load_design(root / 'none', {'extends': 'mine.yaml'}, root)['tokens'],
                             {'a': 1, 'b': 3})
            (root / 'loop.yaml').write_text('extends: loop.yaml\n')
            with self.assertRaisesRegex(design.DesignError, 'too many'):
                design.load_design(root / 'none', str(root / 'loop.yaml'))

    def test_reference_written_by_generator(self):
        with tempfile.TemporaryDirectory() as root:
            design.write_design({'site_directory': root}, design.load_design(REPO / 'themes/slides'))
            self.assertIn('### `gap::`', (Path(root) / 'structure/design.md').read_text())
