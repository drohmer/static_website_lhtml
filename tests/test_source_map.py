"""Source map of the pages (lib/source_map.py): markers of the source lines
through LHTML, then data-lhtml-src="file:line" on the blocks."""
import re
import unittest

import lhtml

from lib import source_map, source_scan

MACROS = {'gap': {'class': 'gap', 'empty': True, 'variant': ['s', 'm', 'l'], 'default': 'm'},
          'credit': {'tag': 'span', 'class': 'credit'},
          'media': {'class': 'media'},
          'demo': {'tag': 'iframe', 'empty': True, 'url': 'src'}}
TAGS = source_scan.value_tags(MACROS)

PAGE = '''{% set layout = 'side' %}
= Title

Some text

media::
img::a.png
credit:: Image ::
::

* item
* other

gap::l
div::(.x)[margin:0]
::[height:25px;]::
::
{% for i in [1, 2] %}
* {{ i }}
{% endfor %}
code::[python]
x = 1
code::[-]
demo::assets/d.html
<div
  class="raw">raw</div>
$$
a < b
$$
'''


def run(text):
    return lhtml.run(text, {'macros': MACROS})


class SourceMapTests(unittest.TestCase):

    def test_value_tags(self):
        self.assertEqual(TAGS, {'img', 'video', 'videoplay', 'link', 'include', 'gap', 'demo'})

    def test_markers_do_not_change_lhtml(self):
        marked = source_map.add_markers(PAGE, TAGS)
        self.assertNotEqual(marked, PAGE)
        self.assertEqual(source_map.strip(run(marked)), run(PAGE))

    def test_where_the_markers_go(self):
        lines = source_map.add_markers(PAGE, TAGS).split('\n')
        m = source_map.marker
        self.assertEqual(lines[0], "{% set layout = 'side' %}")            # Jinja statement: none
        self.assertEqual(lines[1], '= Title' + m(2))
        self.assertEqual(lines[6], m(7) + 'img::a.png')                     # value of a tag: at the start
        self.assertEqual(lines[7], 'credit:: Image ' + m(8) + '::')         # closed on the line
        self.assertEqual(lines[8], '::')                                     # closer: none
        self.assertEqual(lines[13], m(14) + 'gap::l')
        self.assertEqual(lines[21], 'x = 1')                                 # code block: none
        self.assertEqual(lines[25], '  class="raw">raw</div>')               # inside an HTML tag: none
        self.assertEqual(lines[27], 'a < b')                                 # display math: none

    def test_data_src_on_the_top_level_blocks(self):
        html = '<html><body>' + run(source_map.add_markers(PAGE, TAGS)) + '</body></html>'
        result = source_map.apply(html, 'src/a/index.html.j2')
        self.assertNotIn(source_map.OPEN, result)
        found = re.findall(r'<(\w+) data-lhtml-src="src/a/index.html.j2:(\d+)"', result)
        self.assertEqual(found[:6], [('h1', '2'), ('div', '6'), ('ul', '11'), ('div', '14'),
                                     ('div', '15'), ('ul', '19')])     # 16: inside 15

    def test_after_a_code_block(self):
        page = 'code::[python]\nx = 1\ncode::[-]\ndiv::(.small)\ntext\n::\n'
        lines = source_map.add_markers(page, TAGS).split('\n')
        self.assertEqual(lines[:3], ['code::[python]', 'x = 1', 'code::[-]'])
        self.assertEqual(lines[3], 'div::(.small)' + source_map.marker(4))
        result = source_map.apply('<body>' + run(source_map.add_markers(page, TAGS)) + '</body>', 's')
        self.assertIn('<div data-lhtml-src="s:4" class="small">', result)

    def test_jinja_expression_on_several_lines(self):
        page = '{{ parts | join(", ",\n   attribute=None) }}\ntext\n'
        lines = source_map.add_markers(page, TAGS).split('\n')
        self.assertEqual(lines[:2], ['{{ parts | join(", ",', '   attribute=None) }}'])
        self.assertEqual(lines[2], 'text' + source_map.marker(3))

    def test_empty_list_item_and_comment(self):
        page = '* a\n* \n* b ::# note\n'
        self.assertEqual(source_map.add_markers(page, TAGS).split('\n')[1:3], ['* ', '* b ::# note'])
        self.assertEqual(source_map.strip(run(source_map.add_markers(page, TAGS))), run(page))

    def test_blocks_inside_the_wrapper_of_the_theme(self):
        body = run(source_map.add_markers('= Title\n\ntext\n\n* item\n', TAGS))
        html = ('<body><nav>menu</nav><div id="main-content-margin"><div id="main-content-centered">'
                + body + '</div></div></body>')
        found = re.findall(r'<(\w+) data-lhtml-src="s:(\d+)"', source_map.apply(html, 's'))
        self.assertEqual(found, [('h1', '1'), ('ul', '5')])

    def test_without_markers(self):
        self.assertEqual(source_map.apply('<body><p>x</p></body>', 'a'), '<body><p>x</p></body>')


if __name__ == '__main__':
    unittest.main()
