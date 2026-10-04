"""--only (generate some pages of the site), and regressions of the fourth
review: links written through, discovery of the site, ids of titles, deck."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

from lib import deck
from tests.test_deck import REPO, SLIDES, DeckProjectsTests

HEAD = "{% extends 'theme/template/base.html' %}\n{% block content %}\n"


class OnlyTests(DeckProjectsTests):

    def test_only_generates_its_pages(self):
        self.build(self.DECK)
        other = self.site / '01_a/index.html'
        os.utime(other, (0, 0))
        self.write('talk/src/00_plan/index.html.j2', HEAD + "= Plan v2\n{% endblock %}\n")
        structure = self.build(self.DECK, '--only', '00_plan')
        self.assertEqual(other.stat().st_mtime, 0)                      # not generated again
        for name in ('index.html', 'index-2.html'):                       # all the occurrences
            self.assertIn('Plan v2', (self.site / '00_plan' / name).read_text())
        self.assertEqual(len(structure), 4)
        self.assertIn('Plan (2)', (self.site / 'theme/js/menu.js').read_text())
        self.assertFalse(list(self.site.rglob('*.j2')))

    def test_only_reads_included_files_from_the_sources(self):
        self.write('talk/src/01_a/index.html.j2', HEAD + "= A\n{% include '01_a/inc.txt' %}\n{% endblock %}\n")
        self.write('talk/src/01_a/inc.txt', 'first')
        self.build(self.DECK)
        self.write('talk/src/01_a/inc.txt', 'second')
        self.build(self.DECK, '--only', '01_a')
        self.assertIn('second', (self.site / '01_a/index.html').read_text())

    def test_only_unknown_pointer(self):
        self.build(self.DECK)
        output = self.build(self.DECK, '--only', '01_b', ok=False)
        self.assertIn("did you mean '01_a'", output)

    def test_only_keeps_the_previous_version_of_a_failed_page(self):
        self.build(self.DECK)
        before = (self.site / '01_a/index.html').read_text()
        self.write('talk/src/01_a/index.html.j2', HEAD + "{% invalid %}\n{% endblock %}\n")
        self.build(self.DECK, '--only', '01_a', ok=False)
        self.assertEqual((self.site / '01_a/index.html').read_text(), before)

    def test_only_keeps_the_ids_of_the_titles(self):
        config = yaml.safe_load(self.config.read_text())
        config['plugin'] = ['plugins/title_submenu.py', 'plugins/menu.py']
        self.config.write_text(yaml.safe_dump(config))
        self.write('talk/src/00_plan/index.html.j2', HEAD + "= Plan\n== Same\n{% endblock %}\n")
        self.write('talk/src/01_a/index.html.j2', HEAD + "= A\n== Same\n{% endblock %}\n")
        self.build({'slides': ['00_plan', '01_a']})
        full = json.loads((self.site / 'structure/title_id.json').read_text())
        self.build({'slides': ['00_plan', '01_a']}, '--only', '01_a')
        self.assertEqual(json.loads((self.site / 'structure/title_id.json').read_text()), full)
        self.assertIn('id="same_id2_l2"', (self.site / '01_a/index.html').read_text())


class Round4BuildTests(DeckProjectsTests):

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


class Round4DeckTests(unittest.TestCase):

    def test_repeated_page_of_a_directory_with_several_pages_warns(self):
        pages = SLIDES[:2] + [type(SLIDES[0])(SLIDES[0].source, 'a/01_x/', 'extra.html.j2')]
        result = deck.apply_deck(deck.load_deck({'slides': ['a/01_x', 'a/00_section', 'a/01_x']}), pages)
        self.assertEqual(len(result.pages), 3)
        self.assertIn("name its file ('a/01_x/index.html')", result.warnings[0])

    def test_invalid_titles_and_numbers(self):
        for slides, message in (([{'path': 'a', 'title': None}], 'title'),
                                ([{'path': 'a', 'title': ' '}], 'title'),
                                ([0], "quote the path")):
            with self.assertRaisesRegex(deck.DeckError, message):
                deck.load_deck({'slides': slides})


class ReservedConfigTests(unittest.TestCase):

    def test_page_configuration_cannot_set_structure_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'src/a').mkdir(parents=True)
            (root / 'src/a/index.html.j2').write_text('= A\n')
            (root / 'src/a/config.yaml').write_text('template: wide\n')
            (root / 'c.yaml').write_text(yaml.safe_dump({'source_directory': 'src', 'site_directory': 'site'}))
            result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(root / 'c.yaml')],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('reserved key(s) template', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
