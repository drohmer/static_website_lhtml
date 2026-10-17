"""The headings of an LHTML page are those of its document tree
(lib/headings.py, lhtml.parse)."""
import unittest

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


if __name__ == '__main__':
    unittest.main()
