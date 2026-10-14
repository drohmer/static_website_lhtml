"""What the menu publishes in the site.

`theme/js/menu.js` is served to every visitor, so it carries only the keys the
themes need. The settings an author writes for themselves (notes:, message:,
duration: ...) stay out of it.
"""
from pathlib import Path
import json
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

REPO = Path(__file__).resolve().parents[1]
NOTE = 'SPEAKER NOTE THAT MUST NOT BE PUBLISHED'


class MenuPublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml-menu-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        page = self.root / 'src/a'
        page.mkdir(parents=True)
        (page / 'index.html.j2').write_text(
            '{% extends "theme/template/base.html" %}\n{% block content %}\n= Page A\n{% endblock %}\n')
        (page / 'config.yaml').write_text(yaml.safe_dump(
            {'notes': NOTE, 'message': 'draft', 'duration': 5, 'hide-toc': 'False'}))

    def build(self, **options):
        config = self.root / 'configure.yaml'
        config.write_text(yaml.safe_dump({
            'source_directory': 'src', 'site_directory': 'out',
            'theme': str(REPO / 'themes/webpage-frame'), **options}))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = (self.root / 'out/theme/js/menu.js').read_text()
        return text, json.loads(re.search(r'const toc = (\[.*?\]);', text, re.S).group(1))

    def test_private_page_settings_are_not_published(self):
        text, toc = self.build()
        self.assertNotIn(NOTE, text)
        self.assertNotIn('draft', text)
        self.assertEqual(sorted(toc[0]), ['hide-toc', 'level', 'path', 'title'])

    def test_a_theme_can_declare_the_keys_it_needs(self):
        text, toc = self.build(plugin_arg={'menu': {'keys': ['duration']}})
        self.assertIn('duration', toc[0])
        self.assertEqual(toc[0]['duration'], '5')
        self.assertNotIn(NOTE, text)


if __name__ == '__main__':
    unittest.main()
