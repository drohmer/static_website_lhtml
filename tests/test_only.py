"""--only: generate some pages of the site, the others are kept."""
import json
import os
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
                   HEAD + "= A\nverbatim::[]\n* not a list\n= not a title\nverbatim::[-]\n{% endblock %}\n")
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
        self.assertIn('[Warning] 01_a:', output)

    def test_titles_in_code_are_not_headings(self):
        config = yaml.safe_load(self.config.read_text())
        config['plugin'] = ['plugins/title_submenu.py', 'plugins/menu.py']
        self.config.write_text(yaml.safe_dump(config))
        self.write('talk/src/01_a/index.html.j2', "verbatim::[]\n= Not a title\nverbatim::[-]\n" + HEAD
                   + "= A\ncode::[python]\n== x\ncode::[-]\n{% endblock %}\n")
        structure = self.build({'slides': ['01_a']})
        self.assertEqual(structure[0]['title'], 'A')
        headings = json.loads((self.site / 'structure/title_id.json').read_text())['01_a/index.html']
        self.assertEqual([h['title'] for h in headings], ['A'])
        config['title_id'] = False
        self.config.write_text(yaml.safe_dump(config))
        self.build({'slides': ['01_a']})
        self.assertNotIn('id="a_l1"', (self.site / '01_a/index.html').read_text())

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


if __name__ == '__main__':
    unittest.main()
