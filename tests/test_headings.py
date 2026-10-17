"""The headings of an LHTML page are those of its document tree
(lib/headings.py, lhtml.parse)."""
import unittest

from lib.generator_tool import extract_title
from lib.headings import lhtml_headings


class LhtmlHeadings(unittest.TestCase):

    def test_a_heading_is_what_lhtml_reads_as_one(self):
        text = ('= Title **bold**\n'
                'code::[python]\n= not a heading\ncode::[-]\n'
                '<!--\n= nor this\n-->\n'
                '`= nor inline code`\n'
                '==(.c #mine) Section\n')
        self.assertEqual([(level, class_id, title) for _, _, level, class_id, title in lhtml_headings(text)],
                         [(1, '', 'Title **bold**'), (2, '.c #mine', 'Section')])

    def test_its_place_and_its_attributes_are_as_written(self):
        text = 'x\r\n=({{ anchor }}) A {{ name }}\r\n'
        [(start, end, level, class_id, title)] = lhtml_headings(text)
        self.assertEqual((text[start:end], class_id, title), ('=({{ anchor }}) A {{ name }}', '{{ anchor }}',
                                                              'A {{ name }}'))

    def test_a_page_lhtml_refuses_has_none(self):
        self.assertEqual(lhtml_headings('= T\ninclude::other.txt\n'), [])



class PageTitle(unittest.TestCase):

    def test_the_first_heading_of_the_tree(self):
        # a heading with attributes is one (the regular expression took the next)
        self.assertEqual(extract_title('=(#intro) Introduction\n== Next\n'), 'Introduction')
        # nor a line of a code block or a comment
        self.assertEqual(extract_title('code::[text]\n= Not\ncode::[-]\n<!--\n= Nor\n-->\n= Title\n'), 'Title')
        self.assertIsNone(extract_title('no heading\n'))
        self.assertEqual(extract_title("{% set pageTitle = 'Set' %}\n= Title\n"), 'Set')

    def test_jinja_in_the_attributes_of_a_heading(self):
        self.assertEqual(extract_title('=(.c {{ f(a) }}) Title\n'), 'Title')
        [(_, _, _, attributes, title)] = lhtml_headings('=(.c {{ f(a) }}) Title\n')
        self.assertEqual((attributes, title), ('.c {{ f(a) }}', 'Title'))

    def test_the_scanners_of_a_page_share_one_tree(self):
        from unittest.mock import patch
        import lhtml
        from lib import credits, source_scan
        page = source_scan.Scan('= T\nimg::a.png\n')
        macros = {'box': {'class': 'box'}}
        with patch('lhtml.parse', wraps=lhtml.parse) as parse:
            extract_title(page, macros)
            credits.files_used(page, macros)
            credits.files_used(page, macros)
        self.assertEqual(parse.call_count, 1)


if __name__ == '__main__':
    unittest.main()
