"""Builds of a deck with pages of other projects, and of a project without
deck: copies of assets, includes, sitemap ids, scaffold, structure."""
from pathlib import Path
import os
import shutil
import tempfile
import unittest

import yaml

from tests.test_deck import REPO, DeckProjectsTests

HEAD = "{% extends 'theme/template/base.html' %}\n{% block content %}\n"


class ProjectBuildTests(DeckProjectsTests):

    def test_linked_assets_of_another_project_are_copied(self):
        self.write('shared/s.sass', 'a\n  color: red\n')
        os.symlink(self.root / 'shared', self.root / 'course/src/05_b/01_c/style')
        os.symlink('../../../../shared', self.root / 'course/src/05_b/01_c/media')
        self.write('course/src/05_b/01_c/.env', 'secret')
        self.build({'sources': {'course': '../course/src'}, 'slides': ['01_a', 'course:05_b/01_c']})
        page = self.site / 'course/05_b/01_c'
        for name in ('style', 'media'):
            self.assertFalse((page / name).is_symlink())
            self.assertTrue((page / name).is_dir())
        self.assertFalse((page / '.env').exists())
        self.assertEqual(sorted(os.listdir(self.root / 'shared')), ['s.sass'])

    def test_parent_page_assets_with_only(self):
        self.write('course/src/05_b/01_c/nested/index.html.j2', HEAD + "= N\n{% endblock %}\n")
        deck_data = {'sources': {'course': '../course/src'},
                     'slides': ['01_a', 'course:05_b/01_c/nested', 'course:05_b/01_c/index.html']}
        self.build(deck_data)
        (self.site / 'course/05_b/01_c/assets/c.png').unlink()
        self.build(deck_data, '--only', 'course:05_b/01_c')
        self.assertTrue((self.site / 'course/05_b/01_c/assets/c.png').is_file())

    def test_include_of_a_template_not_in_the_deck(self):
        self.write('talk/src/01_a/index.html.j2', HEAD + "= A\n{% include 'parts/box.html.j2' %}\n{% endblock %}\n")
        self.write('talk/src/parts/box.html.j2', 'box:: boxed ::\n')
        for args in ((), ('--only', '01_a')):
            self.build({'slides': ['01_a']}, *args)
            self.assertIn('<div class="box"> boxed </div>', (self.site / '01_a/index.html').read_text())
            self.assertFalse((self.site / 'parts/box.html.j2').exists())
            self.assertFalse((self.site / 'parts/box.html').exists())

    def test_sitemap_link_used_only_in_an_included_file(self):
        self.write('talk/src/01_a/index.html.j2', HEAD + "= A\n{% include '01_a/inc.txt' %}\n{% endblock %}\n")
        self.write('talk/src/01_a/inc.txt', 'link: {{pathTo_plan}}\n')
        self.build({'slides': ['00_plan', '01_a']})
        self.assertIn('link: ../00_plan/index.html', (self.site / '01_a/index.html').read_text())

    def test_scaffold_escapes_the_metadata(self):
        slides = [{'path': '02_new', 'title': 'New {{ one }}\nsecond line',
                   'notes': 'demo {% if %} later', 'hint': 'use {{ x }}'}]
        self.build({'slides': slides}, '--scaffold')
        html = (self.site / '02_new/index.html').read_text()
        self.assertIn('New {{ one }}', html)
        self.assertNotIn('second line', html)
        self.assertTrue((self.site / 'sitemap/new_{{_one_}}.html').is_file())

    def test_occurrence_does_not_replace_a_page_file(self):
        self.write('talk/src/00_plan/index-2.html', 'raw page')
        structure = self.build({'slides': [{'path': '00_plan', 'params': {'current': 1}}, '01_a',
                                           {'path': '00_plan', 'params': {'current': 2}}]})
        self.assertEqual(structure[2]['filename'], 'index-3.html')
        self.assertEqual((self.site / '00_plan/index-2.html').read_text(), 'raw page')

    def test_structure_gives_the_template(self):
        structure = self.build(self.DECK)
        self.assertEqual(structure[3]['template'], '00_plan/index-2.html.j2')
        self.assertNotIn(str(self.root), (self.site / 'theme/js/menu.js').read_text())   # no local path


class SiteDiscoveryTests(DeckProjectsTests):

    def test_file_links_of_the_theme_are_not_written_through(self):
        shared = self.root / 'shared/menu.js'
        theme = self.root / 'theme'
        shutil.copytree(REPO / 'themes/slides', theme)
        shared.parent.mkdir()
        shutil.move(theme / 'js/menu.js', shared)
        os.symlink('../../shared/menu.js', theme / 'js/menu.js')
        before = shared.read_text()
        config = yaml.safe_load(self.config.read_text())
        config['theme'] = str(theme)
        self.config.write_text(yaml.safe_dump(config))
        self.build(self.DECK)
        self.assertEqual(shared.read_text(), before)
        self.assertFalse((self.site / 'theme/js/menu.js').is_symlink())
        self.assertIn('Plan (2)', (self.site / 'theme/js/menu.js').read_text())

    def test_a_link_to_the_site_is_not_discovered(self):
        os.symlink('../site', self.root / 'talk/src/out')
        config = yaml.safe_load(self.config.read_text())
        config['debug'] = True
        del config['deck']                                  # all the pages of the sources
        self.config.write_text(yaml.safe_dump(config))
        for _ in range(2):
            structure = self.build({})
        self.assertEqual([e['dir'] for e in structure], ['00_plan/', '01_a/'])

    def test_scaffolded_title_with_jinja_and_title_ids(self):
        config = yaml.safe_load(self.config.read_text())
        config['plugin'] = ['plugins/title_submenu.py']
        self.config.write_text(yaml.safe_dump(config))
        self.build({'slides': [{'path': '07_new', 'title': 'New {{ slide }}'}]}, '--scaffold')
        self.assertIn('New {{ slide }}', (self.site / '07_new/index.html').read_text())


class WithoutDeckTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml nodeck ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.config = self.root / 'config.yaml'
        self.config.write_text(yaml.safe_dump({'source_directory': 'src', 'site_directory': 'site',
                                               'theme': str(REPO / 'themes/slides')}))

    def write(self, name, text):
        path = self.root / 'src' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def build(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(self.config)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sitemap_ids_in_file_order(self):
        self.write('zz.html.j2', HEAD + "= Intro\n{% endblock %}\n")
        self.write('a/index.html.j2', HEAD + "= Intro\n{{ pathTo_intro }} {{ pathTo_intro_1 }}\n{% endblock %}\n")
        self.build()
        self.assertIn('../zz.html ../a/index.html', (self.root / 'site/a/index.html').read_text())

    def test_hidden_files(self):
        self.write('a/.drafts/index.html.j2', HEAD + "= Draft\n{% endblock %}\n")
        self.write('.top.html.j2', HEAD + "= Top\n{% endblock %}\n")
        self.build()
        self.assertTrue((self.root / 'site/a/.drafts/index.html').is_file())
        self.assertFalse((self.root / 'site/.top.html').exists())


if __name__ == '__main__':
    unittest.main()
