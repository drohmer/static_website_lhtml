"""What the menu publishes in the site.

`theme/js/menu.js` is served to every visitor, so it carries only the keys the
themes need. The settings an author writes for themselves (notes:, message:,
duration: ...) stay out of it.
"""
from pathlib import Path
import json
import os
import re
import shutil
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
        options.setdefault('theme', str(REPO / 'src/lhtml_site/themes/webpage-frame'))
        config.write_text(yaml.safe_dump({
            'source_directory': 'src', 'site_directory': 'out', **options}))
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

    def test_a_theme_declares_the_keys_it_needs(self):
        """The extra keys are the theme's business: a project cannot know
        what its theme's menu displays (theme.yaml, `toc: keys:`)."""
        theme = self.root / 'theme'
        shutil.copytree(REPO / 'src/lhtml_site/themes/webpage-frame', theme)
        (theme / 'theme.yaml').write_text(yaml.safe_dump(
            {'toc': {'file': 'js/menu.js', 'keys': ['duration']}}))
        text, toc = self.build(theme=str(theme))
        self.assertIn('duration', toc[0])
        self.assertEqual(toc[0]['duration'], '5')
        self.assertNotIn(NOTE, text)

    def test_a_theme_with_no_menu_gets_none(self):
        """A theme that declares no `toc:` has no menu, and the build does
        not invent one."""
        theme = self.root / 'bare'
        shutil.copytree(REPO / 'src/lhtml_site/themes/webpage-frame', theme)
        (theme / 'theme.yaml').write_text('template: \'theme/template/base.html\'\n')
        config = self.root / 'configure.yaml'
        config.write_text(yaml.safe_dump({
            'source_directory': 'src', 'site_directory': 'bare-out', 'theme': str(theme)}))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # the file is copied with the theme, but its placeholder is untouched
        self.assertIn('{{TOC}}', (self.root / 'bare-out/theme/js/menu.js').read_text())


@unittest.skipUnless(os.environ.get('LHTML_BROWSER_TEST') == '1', 'Set LHTML_BROWSER_TEST=1 for Chromium')
class QuietConsoleTests(unittest.TestCase):
    """A page opened from disk writes nothing in the console of the
    browser: no error, and no debugging left in the scripts of the theme."""

    def test_the_slides_starter_is_silent(self):
        self.assertSilent('slides')

    def test_the_website_starter_is_silent(self):
        self.assertSilent('webpage-frame')

    def assertSilent(self, theme):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('playwright')
        with tempfile.TemporaryDirectory(prefix='lhtml-console-') as temp:
            project = Path(temp) / 'talk'
            generate = [sys.executable, str(REPO / 'generate.py')]
            subprocess.run(generate + ['init', str(project), '--theme', theme], check=True, capture_output=True)
            subprocess.run(generate, cwd=project, check=True, capture_output=True)
            pages = sorted((project / '.site').glob('*/index.html'))
            self.assertTrue(pages)
            messages = []
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.on('console', lambda m: messages.append(f'{m.type}: {m.text}'))
                page.on('pageerror', lambda e: messages.append(f'error: {e}'))
                for path in pages:
                    page.goto(path.as_uri(), wait_until='load')
                    page.wait_for_timeout(300)
                browser.close()
            self.assertEqual(messages, [])


if __name__ == '__main__':
    unittest.main()
