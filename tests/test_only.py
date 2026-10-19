"""--only: generate some pages of the site, the others are kept."""
import json
import os
import re
import unittest

import yaml

from tests.test_deck import DeckProjectsTests

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
        self.assertIn("did you mean '01_a'", ' '.join(output.split()))

    def test_only_keeps_the_previous_version_of_a_failed_page(self):
        self.write('talk/src/01_a/index.html.j2',
                   HEAD + "= A\ncode::[text]\n* not a list\n= not a title\ncode::[-]\n{% endblock %}\n")
        self.build(self.DECK)
        before = (self.site / '01_a/index.html').read_text()
        self.assertIn('* not a list', before)
        for error in ("{% invalid %}", "{{ undefined_function() }}"):
            self.write('talk/src/01_a/index.html.j2', HEAD + error + "\n{% endblock %}\n")
            self.build(self.DECK, '--only', '01_a', ok=False)
            # put back as it was, not converted by LHTML a second time
            self.assertEqual((self.site / '01_a/index.html').read_text(), before)

    def test_a_failed_page_does_not_stop_the_plugins(self):
        """The plugins after the rendering (code_include) only see the pages generated."""
        config = yaml.safe_load(self.config.read_text())
        config['plugin'] = ['plugins/code_include.py']
        self.config.write_text(yaml.safe_dump(config))
        self.write('talk/code/lib/f.hpp', 'int foo();\nint bar();\n')
        self.write('talk/src/01_a/index.html.j2', HEAD + "= A\ncode::[c++]\n"
                   "includeadv::{filepath:'lib/f.hpp', research:'bar'}\ncode::[-]\n{% endblock %}\n")
        deck = {'slides': ['00_plan', '01_a']}
        self.build(deck)
        self.write('talk/src/00_plan/index.html.j2', HEAD + "{{ undefined_fn() }}\n{% endblock %}\n")
        output = self.build(deck, '--only', '00_plan', '--only', '01_a', ok=False)
        self.assertNotIn('FileNotFoundError', output)
        self.assertIn('1 page(s) failed', output)
        html = (self.site / '01_a/index.html').read_text()
        self.assertIn('bar', html)
        self.assertNotIn('includeadv', html)

    def test_lhtml_warnings_name_their_page(self):
        self.write('talk/src/01_a/index.html.j2', HEAD + "= A\ngap::zz\n{% endblock %}\n")
        output = ' '.join(self.build(self.DECK, '--only', '01_a', ok=None).split())
        self.assertIn('talk/src/01_a/index.html.j2:4:1: warning: gap::zz: unknown variant', output)

    def test_titles_in_code_are_not_headings(self):
        config = yaml.safe_load(self.config.read_text())
        config['plugin'] = []
        self.config.write_text(yaml.safe_dump(config))
        self.write('talk/src/01_a/index.html.j2', "{# = Not a title #}\n" + HEAD
                   + "= A\ncode::[python]\n== x\ncode::[-]\n{% endblock %}\n")
        structure = self.build({'slides': ['01_a']})
        self.assertEqual(structure[0]['title'], 'A')
        headings = json.loads(self.headings.read_text())['01_a/index.html']
        self.assertEqual([h['title'] for h in headings], ['A'])
        config['title_id'] = False
        self.config.write_text(yaml.safe_dump(config))
        self.build({'slides': ['01_a']})
        self.assertNotIn('id="a_l1"', (self.site / '01_a/index.html').read_text())

    def test_only_keeps_the_ids_of_the_titles(self):
        config = yaml.safe_load(self.config.read_text())
        config['plugin'] = []
        self.config.write_text(yaml.safe_dump(config))
        self.write('talk/src/00_plan/index.html.j2', HEAD + "= Plan\n== Same\n{% endblock %}\n")
        self.write('talk/src/01_a/index.html.j2', HEAD + "= A\n== Same\n{% endblock %}\n")
        self.build({'slides': ['00_plan', '01_a']})
        full = json.loads(self.headings.read_text())
        self.build({'slides': ['00_plan', '01_a']}, '--only', '01_a')
        self.assertEqual(json.loads(self.headings.read_text()), full)
        self.assertIn('id="same_id2_l2"', (self.site / '01_a/index.html').read_text())

    def test_the_headings_are_build_state_not_published(self):
        """Their record is kept next to the dependency store; the site holds
        no title_id.json (3.0 wrote one per page, and a copy for an index)."""
        self.write('talk/src/00_plan/index.html.j2', HEAD + "= Plan\n== Same\n{% endblock %}\n")
        self.write('talk/src/01_a/index.html.j2', HEAD + "= A\n== Same\n{% endblock %}\n")
        self.build({'slides': ['00_plan', '01_a']})
        self.assertEqual(sorted(p.name for p in self.site.rglob('*title_id*.json')), [])
        self.assertEqual([h['id'] for h in json.loads(self.headings.read_text())['01_a/index.html']],
                         ['a_l1', 'same_id2_l2'])
        # A site built by 3.0: its record was in the site, read once by --only
        legacy = {page: headings for page, headings in json.loads(self.headings.read_text()).items()}
        self.headings.unlink()
        (self.site / 'structure/title_id.json').write_text(json.dumps(legacy))
        self.build({'slides': ['00_plan', '01_a']}, '--only', '01_a')
        self.assertIn('id="same_id2_l2"', (self.site / '01_a/index.html').read_text())
        self.assertTrue(self.headings.is_file())

    def test_a_failed_build_keeps_the_record_of_the_previous_one(self):
        self.write('talk/src/00_plan/index.html.j2', HEAD + "= Plan\n{% endblock %}\n")
        self.write('talk/src/01_a/index.html.j2', HEAD + "= A\n{% endblock %}\n")
        self.build({'slides': ['00_plan', '01_a']})
        before = self.headings.read_text()
        self.write('talk/src/00_plan/index.html.j2', HEAD + "= Other\n{{ undefined_function() }}\n{% endblock %}\n")
        self.build({'slides': ['00_plan', '01_a']}, ok=False)
        self.assertEqual(self.headings.read_text(), before)

    def test_a_heading_from_jinja_gets_its_id_from_its_rendered_text(self):
        """A template reused with params: each occurrence gets the id of its
        own heading, as rendered (3.0 gave both '_parts[params_curr_l1'),
        each heading of a loop its own, and the headings written as text
        keep their ids (those of the sites already published)."""
        self.write('talk/src/00_plan/index.html.j2', HEAD
                   + "{% set parts = ['Intro', 'Rotations (3D)'] %}\n"
                     "= {{ parts[params.current - 1] }}\n"
                     "{% for s in ['Same', 'Same'] %}\n== {{ s }}\n{% endfor %}\n"
                     "== Same\n"
                     "== {% raw %}{{ kept }}{% endraw %}\n{% endblock %}\n")
        self.write('talk/src/01_a/index.html.j2', HEAD + "= A\n== Same\n{% endblock %}\n")
        deck = {'slides': [{'path': '00_plan', 'params': {'current': 1}}, '01_a',
                           {'path': '00_plan', 'params': {'current': 2}}]}
        for args in ((), ('--only', '00_plan')):
            self.build(deck, *args)
            first = (self.site / '00_plan/index.html').read_text()
            second = (self.site / '00_plan/index-2.html').read_text()
            self.assertIn('<h1 id="intro_l1">Intro</h1>', first)
            self.assertIn('<h1 id="rotations_3d__l1">Rotations (3D)</h1>', second)
            # The headings written as text: unique in the site, as in 3.0
            # (00_plan/index.html, 01_a, then 00_plan/index-2.html)
            self.assertIn('<h2 id="same_l2">Same</h2>\n\n<h2 id="_kept__l2">', first)
            self.assertIn('<h2 id="same_id2_l2">Same</h2>', (self.site / '01_a/index.html').read_text())
            self.assertIn('<h2 id="same_id3_l2">Same</h2>\n\n<h2 id="_kept__id2_l2">', second)
            # those of the loop: from their text, unique in their page
            self.assertEqual(re.findall(r'<h2 id="(\w+)">Same', first), ['same_id2_l2', 'same_id3_l2', 'same_l2'])
            self.assertEqual(re.findall(r'<h2 id="(\w+)">Same', second), ['same_l2', 'same_id2_l2', 'same_id3_l2'])

    @property
    def headings(self):
        return self.root / 'talk/.verification/headings.json'


if __name__ == '__main__':
    unittest.main()
