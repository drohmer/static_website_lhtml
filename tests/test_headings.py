"""The headings of an LHTML page are those of its document tree
(lhtml_site/headings.py, lhtml.parse)."""
import unittest

from lhtml_site.generator_tool import extract_title
from lhtml_site.headings import generate_new_id, lhtml_headings


class HeadingIds(unittest.TestCase):
    """The ids of the last copied generator (title_submenu.py, April 2026),
    used by the sites it built: links into them keep working."""

    def test_the_ids_of_the_previous_generator(self):
        for title, expected in [('Simulation - Mass-springs Cloth', 'simulation__mass_spr'),
                                ('Ani3D - Introduction', 'ani3d__introduction'),
                                ('Animating fluids (I)', 'animating_fluids_i_'),
                                ('Exemple CMakeLists.txt', 'exemple_cmakelists_t'),
                                ('std::vector, exemples', 'std_vector_exemples'),
                                ('Solve: x = A(b)', 'solve_x_=_a_b_')]:
            self.assertEqual(generate_new_id(title, {}), expected, title)

    def test_unsafe_characters_are_removed(self):
        self.assertEqual(generate_new_id('A <b> & "c"\t{% raw %}d{% endraw %}', {}), 'a_b_cd')

    def test_a_repeated_heading_gets_distinct_ids(self):
        storage = {}
        self.assertEqual([generate_new_id('Part - One', storage) for _ in range(3)],
                         ['part__one', 'part__one_id2', 'part__one_id3'])


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
        from lhtml_site import credits, source_scan
        page = source_scan.Scan('= T\nimg::a.png\n')
        macros = {'box': {'class': 'box'}}
        with patch('lhtml.parse', wraps=lhtml.parse) as parse:
            extract_title(page, macros)
            credits.files_used(page, macros)
            credits.files_used(page, macros)
        self.assertEqual(parse.call_count, 1)


if __name__ == '__main__':
    unittest.main()
