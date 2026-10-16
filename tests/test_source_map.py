"""Source map of the pages (lib/source_map.py): markers of the source lines
through LHTML, then data-lhtml-src="file:line" on the blocks."""
import os
import re
import unittest

import jinja2
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
        marked = source_map.add_markers(PAGE, 's', TAGS)
        self.assertNotEqual(marked, PAGE)
        self.assertEqual(source_map.strip(run(marked)), run(PAGE))

    def test_where_the_markers_go(self):
        lines = source_map.add_markers(PAGE, 's', TAGS).split('\n')
        m = source_map.marker
        self.assertEqual(lines[0], "{% set layout = 'side' %}")            # Jinja statement: none
        self.assertEqual(lines[1], '= Title' + m('s:2'))
        self.assertEqual(lines[6], m('s:7', True) + 'img::a.png')               # value of a tag: at the start
        self.assertEqual(lines[7], 'credit:: Image ' + m('s:8') + '::')         # closed on the line
        self.assertEqual(lines[8], '::')                                     # closer: none
        self.assertEqual(lines[13], m('s:14', True) + 'gap::l')
        self.assertEqual(lines[21], 'x = 1')                                 # code block: none
        self.assertEqual(lines[25], '  class="raw">raw</div>')               # inside an HTML tag: none
        self.assertEqual(lines[27], 'a < b')                                 # display math: none

    def test_data_src_on_the_top_level_blocks(self):
        html = '<html><body>' + run(source_map.add_markers(PAGE, 'src/a/index.html.j2', TAGS)) + '</body></html>'
        result = source_map.apply(html)
        self.assertNotIn(source_map.OPEN, result)
        found = re.findall(r'<(\w+) data-lhtml-src="src/a/index.html.j2:(\d+)"', result)
        self.assertEqual(found[:6], [('h1', '2'), ('div', '6'), ('ul', '11'), ('div', '14'),
                                     ('div', '15'), ('ul', '19')])     # 16: inside 15

    def test_after_a_code_block(self):
        page = 'code::[python]\nx = 1\ncode::[-]\ndiv::(.small)\ntext\n::\n'
        lines = source_map.add_markers(page, 's', TAGS).split('\n')
        self.assertEqual(lines[:3], ['code::[python]', 'x = 1', 'code::[-]'])
        self.assertEqual(lines[3], 'div::(.small)' + source_map.marker('s:4'))
        result = source_map.apply('<body>' + run(source_map.add_markers(page, 's', TAGS)) + '</body>')
        self.assertIn('<div data-lhtml-src="s:4" class="small">', result)

    def test_jinja_expression_on_several_lines(self):
        page = '{{ parts | join(", ",\n   attribute=None) }}\ntext\n'
        lines = source_map.add_markers(page, 's', TAGS).split('\n')
        self.assertEqual(lines[:2], ['{{ parts | join(", ",', '   attribute=None) }}'])
        self.assertEqual(lines[2], 'text' + source_map.marker('s:3'))

    def test_empty_list_item_and_comment(self):
        page = '* a\n* \n* b ::# note\n'
        self.assertEqual(source_map.add_markers(page, 's', TAGS).split('\n')[1:3], ['* ', '* b ::# note'])
        self.assertEqual(source_map.strip(run(source_map.add_markers(page, 's', TAGS))), run(page))

    def test_blocks_inside_the_wrapper_of_the_theme(self):
        body = run(source_map.add_markers('= Title\n\ntext\n\n* item\n', 's', TAGS))
        html = ('<body><nav>menu</nav><div id="main-content-margin"><div id="main-content-centered">'
                + body + '</div></div></body>')
        found = re.findall(r'<(\w+) data-lhtml-src="s:(\d+)"', source_map.apply(html))
        self.assertEqual(found, [('h1', '1'), ('ul', '5')])

    def test_html_and_macros_on_one_line(self):
        """Each block written on one line in HTML, or by a macro, gets its own line."""
        page = ('= Title\n<div class="note">text</div>\n<div class="other">more</div>\n<img src="a.png">\n'
                "{{ box('first') }}\n{{ box('second') }}\n")
        marked = source_map.add_markers(page, 's', TAGS)
        self.assertIn('text' + source_map.marker('s:2') + '</div>', marked)        # before the final tag
        rendered = marked.replace("{{ box('first') }}", '<div class="box">first</div>')
        rendered = rendered.replace("{{ box('second') }}", '<div class="box">second</div>')
        found = re.findall(r'<(\w+) data-lhtml-src="s:(\d+)"', source_map.apply('<body>' + run(rendered) + '</body>'))
        self.assertEqual(found, [('h1', '1'), ('div', '2'), ('div', '3'), ('img', '4'), ('div', '5'), ('div', '6')])

    def test_same_html_with_line_breaks(self):
        page = 'line one<br>\n\nline two\n<b>bold</b>\ntext <i>it</i>\n'
        options = {'macros': MACROS, 'line-breaks': True}
        self.assertEqual(source_map.strip(lhtml.run(source_map.add_markers(page, 's', TAGS), options)),
                         lhtml.run(page, options))

    def test_no_markers_in_the_value_blocks_of_jinja(self):
        page = ('{% set word %}\nhello\n{% endset %}\n{% markdown %}\nTitle\n-----\n{% endmarkdown %}\n'
                '{% filter upper %}\nloud\n{% endfilter %}\nafter\n')
        lines = source_map.add_markers(page, 's', TAGS).split('\n')
        self.assertEqual(lines[:10], page.split('\n')[:10])
        self.assertEqual(lines[10], 'after' + source_map.marker('s:11'))

    def test_same_html_through_jinja(self):
        page = ('{% set word %}\nhello\n{% endset %}\n{% if word|trim == "hello" %}EQUAL{% endif %}\n'
                '{% markdown %}\nTitle\n-----\n\n---\n{% endmarkdown %}\n= End\n')
        env = jinja2.Environment(extensions=['jinja_markdown.MarkdownExtension'])
        render = lambda text: run(env.from_string(text).render())
        self.assertIn('EQUAL', render(page))
        self.assertEqual(source_map.strip(render(source_map.add_markers(page, 's', TAGS))), render(page))

    def test_empty_heading_with_a_class(self):
        page = '=(.x) \ntext\n'
        self.assertEqual(source_map.add_markers(page, 's', TAGS).split('\n')[0], '=(.x) ')
        self.assertEqual(source_map.strip(run(source_map.add_markers(page, 's', TAGS))), run(page))

    def test_a_block_with_no_marker_of_its_own_says_so(self):
        """The build marks the lines of the page template and of nothing
        else, so a block that comes from an included file takes the line of
        the marker before it: a line of the page, holding another block.
        It is marked as a landmark (data-lhtml-near), because a report that
        states it as the position of the block sends its reader to another
        block."""
        page = 'Une ligne de texte de la page\n{% include "inc.j2" %}\n'
        rendered = run(source_map.add_markers(page, 's', TAGS)).replace(
            '{% include "inc.j2" %}', '<p>venu du fichier inclus</p>')
        result = source_map.apply('<body>' + rendered + '</body>')
        self.assertIn('<p data-lhtml-src="s:1" data-lhtml-near="1">', result)
        self.assertNotIn(source_map.OPEN, result)

        # a block holding the marker of its own line keeps it plain
        own = source_map.apply('<body>' + run(source_map.add_markers(
            'div::(.x)\ntexte\n::\n', 's', TAGS)) + '</body>')
        self.assertIn('<div data-lhtml-src="s:1" class="x">', own)
        self.assertNotIn('data-lhtml-near', own)

    def test_a_block_written_as_the_value_of_a_tag_is_on_its_own_line(self):
        """`gap::l` and `img::a.png` take their marker at the start of the
        line, because a marker at the end would become part of the value.
        The block that follows it is the one that line writes, so the line
        is its own - 100 of the 107 blocks of a real deck that used to be
        reported 'near line n' where n was exactly right."""
        page = 'texte\ngap::l\nimg::a.png\n<img src="b.png">\n'
        result = source_map.apply('<body>' + run(source_map.add_markers(page, 's', TAGS)) + '</body>')
        for line in ('2', '3', '4'):
            self.assertIn(f'data-lhtml-src="s:{line}"', result)
        self.assertNotIn('data-lhtml-near', result)

    def test_without_markers(self):
        self.assertEqual(source_map.apply('<body><p>x</p></body>'), '<body><p>x</p></body>')


def test_a_source_is_named_relative_to_the_project_never_to_the_machine():
    """The marker is published in every page of a --layout build: a source
    outside the configuration directory must not be named by a path that
    climbs out of it ('../../../Users/...')."""
    label = source_map.source_label
    assert label('/p/src/a/index.html.j2', '/p/', '/p/src/') == os.path.join('src', 'a', 'index.html.j2')
    assert label('/elsewhere/deck/src/b.html.j2', '/p/', '/elsewhere/deck/src/') == 'b.html.j2'
    assert label('/anywhere/c.html.j2', '/p/', '/p/src/') == 'c.html.j2'
    for src in ('/elsewhere/deck/src/b.html.j2', '/anywhere/c.html.j2'):
        assert not label(src, '/p/', '/p/src/').startswith('..')


if __name__ == '__main__':
    unittest.main()
