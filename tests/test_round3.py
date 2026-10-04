"""Regressions of the third review: copies of linked directories, sitemap ids,
Jinja includes, light mode, scaffold, watch, hidden files."""
from pathlib import Path
import os
import tempfile
import unittest

import yaml

from lib import deck, design, filesystem
from lib.configuration import ConfigError, load_config
from tests.test_deck import REPO, DeckProjectsTests

HEAD = "{% extends 'theme/template/base.html' %}\n{% block content %}\n"


class CopyTreeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml copy ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def write(self, name, text='x'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_relative_link_in_a_linked_directory_still_resolves(self):
        self.write('ext/img/logo.png', 'logo')
        (self.root / 'ext/common').mkdir(parents=True)
        os.symlink('../img/logo.png', self.root / 'ext/common/logo.png')
        self.write('src/a.txt')
        os.symlink('../ext/common', self.root / 'src/shared')
        os.symlink('a.txt', self.root / 'src/b.txt')
        filesystem.copy_directories(self.root / 'src', self.root / 'site')
        self.assertFalse((self.root / 'site/shared').is_symlink())
        self.assertEqual((self.root / 'site/shared/logo.png').read_text(), 'logo')
        self.assertEqual(os.readlink(self.root / 'site/b.txt'), 'a.txt')    # stays relative

    def test_link_to_the_site_and_to_an_ancestor(self):
        self.write('src/a.txt')
        self.write('_site/html/index.html')
        os.symlink('../_site', self.root / 'src/out')
        (self.root / 'src/b').mkdir()
        os.symlink('..', self.root / 'src/b/parent')
        os.symlink(str(self.root / 'src'), self.root / 'src/absolute')
        staging = self.root / '_site/.site-build-1'
        warnings = filesystem.copy_directories(self.root / 'src', staging,
                                               exclude=[self.root / '_site/html'])
        self.assertEqual(sorted(os.listdir(staging / 'out')), [])       # neither the site nor the copy
        self.assertEqual(os.readlink(staging / 'b/parent'), '..')
        self.assertFalse((staging / 'absolute').exists())
        self.assertEqual(len(warnings), 1)


class Round3BuildTests(DeckProjectsTests):

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

    def test_parent_page_assets_in_light_mode(self):
        self.write('course/src/05_b/01_c/nested/index.html.j2', HEAD + "= N\n{% endblock %}\n")
        self.build({'sources': {'course': '../course/src'}, 'slides': ['01_a']})
        self.build({'sources': {'course': '../course/src'},
                    'slides': ['01_a', 'course:05_b/01_c/nested', 'course:05_b/01_c/index.html']}, '-l')
        self.assertTrue((self.site / 'course/05_b/01_c/assets/c.png').is_file())

    def test_include_of_a_template_not_in_the_deck(self):
        self.write('talk/src/01_a/index.html.j2', HEAD + "= A\n{% include 'parts/box.html.j2' %}\n{% endblock %}\n")
        self.write('talk/src/parts/box.html.j2', 'box:: boxed ::\n')
        for args in ((), ('-l',)):
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


class Round3WithoutDeckTests(unittest.TestCase):
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


class Round3ConfigTests(unittest.TestCase):
    def test_params_keyword_is_reserved(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'c.yaml'
            (Path(temp) / 'src').mkdir()
            config.write_text(yaml.safe_dump({'source_directory': 'src', 'keywords': {'params': 1}}))
            with self.assertRaises(ConfigError):
                load_config(config)

    def test_watched_paths_of_a_file_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / 'ext/e1').mkdir(parents=True)
            (root / 'ext/e1/index.html.j2').write_text('= E\n')
            paths = deck.watched_paths({'sources': {'x': 'ext'}, 'slides': ['x:e1/index.html', 'x:e1/index']},
                                       root)
            self.assertEqual(paths, [root / 'ext/e1', root / 'ext/e1'])

    def test_design_files_follow_extends(self):
        files = design.design_files(REPO / 'themes/slides-pdf')
        self.assertEqual([f.resolve() for f in files],
                         [(REPO / 'themes/slides-pdf/design.yaml').resolve(),
                          (REPO / 'themes/slides/design.yaml').resolve()])


if __name__ == '__main__':
    unittest.main()
