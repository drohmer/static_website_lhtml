"""Reading of the sources (lib/source_scan.py), with the patterns of LHTML."""
import re
import unittest

from lhtml import patterns

from lib import source_scan


class PatternsOfLhtmlTests(unittest.TestCase):
    """lib/source_scan.py reads the sources with lhtml.patterns: a new version
    of LHTML that changes them must fail here, not give wrong source lines."""

    def test_the_patterns_used_exist(self):
        for name in ('PROTECTED_BLOCKS', 'COMMENT', 'URL_TAGS', 'URL_TOKEN'):
            self.assertTrue(hasattr(patterns, name), name)
        self.assertLessEqual(set(source_scan.KINDS), set(patterns.PROTECTED_BLOCKS.groupindex))

    def test_each_kind_of_zone(self):
        text = ('verbatim::[]\nv\nverbatim::[-]\ncode::[python]\nc\ncode::[-]\n{{ j }}\n<!-- h -->\n'
                '<script>s</script>\n`i`\nimg::a.png\n$m$\n<b>\n::# l\n')
        kinds = [z.kind for z in source_scan.zones(text)]
        for kind in source_scan.KINDS + (source_scan.LHTML_COMMENT,):
            self.assertIn(kind, kinds)


class ScanTests(unittest.TestCase):

    def test_scan_is_computed_once(self):
        scan = source_scan.Scan('= T\n`= not a title`\n')
        self.assertIs(scan.zones, scan.zones)
        self.assertIs(source_scan.scan(scan), scan)
        self.assertEqual(len(scan.masked), len(scan.text))

    def test_find_skips_code_and_keeps_the_text(self):
        text = 'code::[python]\n= x\ncode::[-]\n= Title `code`\n'
        found = source_scan.find(re.compile(r'^= (.*)$', re.MULTILINE), text)
        self.assertEqual([text[m.start(1):m.end(1)] for m in found], ['Title `code`'])

    def test_layout_setting(self):
        self.assertEqual(source_scan.layout_setting("code::[j]\n{% set layout = 'a' %}\ncode::[-]\n"), None)
        self.assertEqual(source_scan.layout_setting("= T\n{% set layout = 'side' %}\n")[:2], ('side', 2))

    def test_leading_settings_one_tag_per_line(self):
        self.assertEqual(source_scan.leading_settings('{% set n = 2 %}{% if n > 1 %}\n= Big\n'), '')
        self.assertEqual(source_scan.leading_settings('{# a #}{% if x %}{# b #}\nx\n'), '')
        top = "{% set n = 2 -%}\n{# a #}\n::# c\n{% import 'x' as y %}\n"
        self.assertEqual(source_scan.leading_settings(top + '= T\n'), top)


if __name__ == '__main__':
    unittest.main()
