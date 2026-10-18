"""What an extension writes, the core wraps.

These tests used to pin the order of the pair pre_include / auto_wrap,
whose result depended on which came first in the `plugin:` list - and one
of them pinned the bad outcome: auto_wrap first put the included text above
{% extends %}, so it landed before <!DOCTYPE html> and the browser rendered
in quirks mode. It was pinned as it was, not endorsed.

The wrapping is a stage of the build now (lhtml_site/wrap.py), and it runs after
the extensions of the pre stage. The bad order is no longer something a
configuration can express, which is why the ordering debt of the extensions
is settled rather than registered.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

REPO = Path(__file__).resolve().parents[1]
MARKER = 'MARKER_OF_THE_INCLUDED_FILE'


class CoreWrapsWhatExtensionsWriteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml-stage-order-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / 'src').mkdir()
        # A page without {% block content %}: the core is what wraps it.
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

    def test_what_an_extension_writes_is_inside_the_document(self):
        html = self.build(['pre_include'], 'site')
        self.assertIn(MARKER, html)
        self.assertLess(html.index('<!DOCTYPE html>'), html.index(MARKER),
                        'the included content belongs inside the document')
        self.assertIn('Body of the page.', html)

    def test_the_order_that_used_to_break_it_cannot_be_written_any_more(self):
        """`plugin:` listing auto_wrap is refused by name: the build runs the
        wrapping itself, so no configuration can put it before an extension."""
        config = self.root / 'configure_old.yaml'
        config.write_text(yaml.safe_dump({
            'source_directory': 'src', 'site_directory': 'old',
            'plugin': ['plugins/auto_wrap.py', 'plugins/pre_include.py'],
            'plugin_arg': {'pre_include': ['include.j2']}}))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('auto_wrap.py', ' '.join(result.stdout.split()))
        self.assertFalse((self.root / 'old').exists())


if __name__ == '__main__':
    unittest.main()
