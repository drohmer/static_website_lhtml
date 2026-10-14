"""Order of the plugins that rewrite the same template.

The plugins of the 'pre' hook work on the file of the page, one after the
other, in the order of the configuration: what one writes, the next one reads.
These tests pin the current semantics of the pair pre_include / auto_wrap,
whose result depends on that order, so that a change of the plugin system
shows it instead of moving it silently.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

REPO = Path(__file__).resolve().parents[1]
MARKER = 'MARKER_OF_THE_INCLUDED_FILE'


class PluginOrderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml-plugin-order-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / 'src').mkdir()
        # A page without {% block content %}: auto_wrap is the one that wraps it.
        (self.root / 'src/index.html.j2').write_text('= Title\nBody of the page.\n')
        (self.root / 'include.j2').write_text(MARKER + '\n')

    def build(self, plugins, site):
        config = self.root / f'configure_{site}.yaml'
        config.write_text(yaml.safe_dump({
            'source_directory': 'src', 'site_directory': site,
            'plugin': [f'plugins/{name}.py' for name in plugins],
            'plugin_arg': {'pre_include': ['include.j2']}}))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return (self.root / site / 'index.html').read_text()

    def test_pre_include_before_auto_wrap_puts_the_include_in_the_page(self):
        html = self.build(['pre_include', 'auto_wrap'], 'site_included_first')
        self.assertIn(MARKER, html)
        self.assertLess(html.index('<!DOCTYPE html>'), html.index(MARKER),
                        'the included content belongs inside the document')
        self.assertIn('Body of the page.', html)

    def test_auto_wrap_before_pre_include_puts_the_include_outside_the_document(self):
        """The reverse order wraps the page first, so the include lands above
        {% extends %}: the text is written before <!DOCTYPE html> (the browser
        then renders in quirks mode). Pinned as it is today, not endorsed."""
        html = self.build(['auto_wrap', 'pre_include'], 'site_wrapped_first')
        self.assertIn(MARKER, html)
        self.assertLess(html.index(MARKER), html.index('<!DOCTYPE html>'))
        self.assertIn('Body of the page.', html)


if __name__ == '__main__':
    unittest.main()
