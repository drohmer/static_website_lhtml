from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from lib import deck
from lib.configuration import ConfigError, load_config
from lib.filesystem import FilepathRelative

REPO = Path(__file__).resolve().parents[1]


def pages(*paths):
    """Template entries in file order, as find_files_in_hierarchy returns them."""
    result = []
    for path in paths:
        directory, _, filename = path.rpartition('/')
        directory = directory + '/' if directory else ''
        result.append({'path': FilepathRelative(root_directory='/site/', path_local=directory,
                                                filename=filename, level=directory.count('/'))})
    return result


SLIDES = pages('a/00_section/index.html.j2', 'a/01_x/index.html.j2', 'a/02_y/index.html.j2',
               'a/03_todo_z/index.html.j2', 'b/00_section/index.html.j2', 'b/01_w/index.html.j2')


def order(slides, source=SLIDES):
    result = deck.apply_deck(deck.load_deck({'slides': slides}), source)
    return [deck.page_id(p) for p in result.pages], result


class DeckTests(unittest.TestCase):
    def test_directories_keep_file_order(self):
        ids, result = order(['b', 'a'])
        self.assertEqual(ids, ['b/00_section', 'b/01_w', 'a/00_section', 'a/01_x', 'a/02_y', 'a/03_todo_z'])
        self.assertEqual(result.unlisted, [])

    def test_explicit_pointer_moves_page(self):
        ids, _ = order(['a', 'a/01_x'])
        self.assertEqual(ids, ['a/00_section', 'a/02_y', 'a/03_todo_z', 'a/01_x'])
        ids, _ = order(['a/02_y', 'a'])
        self.assertEqual(ids, ['a/02_y', 'a/00_section', 'a/01_x', 'a/03_todo_z'])

    def test_glob_exclusion_and_unlisted(self):
        ids, result = order(['a/0*', '!*todo*'])
        self.assertEqual(ids, ['a/00_section', 'a/01_x', 'a/02_y'])
        self.assertEqual([deck.page_id(p) for p in result.unlisted], ['a/03_todo_z', 'b/00_section', 'b/01_w'])

    def test_metadata(self):
        ids, result = order([{'path': 'a/01_x', 'title': 'X', 'duration': 2}, 'b/01_w/'])
        self.assertEqual(ids, ['a/01_x', 'b/01_w'])
        self.assertEqual(result.pages[0]['deck'], {'title': 'X', 'duration': 2})
        self.assertEqual(deck.total_duration(result.pages), (2, 1))

    def test_listed_and_excluded_warns(self):
        ids, result = order(['a/01_x', 'b', '!a/*'])
        self.assertEqual(ids, ['b/00_section', 'b/01_w'])
        self.assertIn('also excluded', result.warnings[0])

    def test_repeated_pointer_gives_occurrences(self):
        ids, result = order([{'path': 'a/01_x', 'params': {'current': 1}}, 'b',
                             {'path': 'a/01_x', 'params': {'current': 2}}, 'a'])
        self.assertEqual(ids, ['a/01_x', 'b/00_section', 'b/01_w', 'a/01_x',
                               'a/00_section', 'a/02_y', 'a/03_todo_z'])
        self.assertEqual([p.get('occurrence', 1) for p in result.pages[:4]], [1, 1, 1, 2])
        self.assertEqual(result.pages[0]['deck']['params'], {'current': 1})
        self.assertEqual(result.pages[3]['deck']['params'], {'current': 2})
        self.assertEqual(result.warnings, [])

    def test_several_pages_in_a_directory(self):
        site = pages('index.html.j2', 'course/intro.html.j2', 'course/index.html.j2')
        ids, result = order(['course/intro.html', 'index.html', 'course'], site)
        self.assertEqual([deck.page_file(p) for p in result.pages],
                         ['course/intro.html', 'index.html', 'course/index.html'])

    def test_unknown_pointer(self):
        with self.assertRaisesRegex(deck.DeckError, "did you mean 'a/01_x'"):
            order(['a/01_xx'])

    def test_planned_slide_and_unused_exclusion(self):
        ids, result = order(['a/01_x', {'path': 'a/09_new', 'title': 'New'}, '!c/*'])
        self.assertEqual(ids, ['a/01_x'])
        self.assertEqual([e.pointer for e in result.missing], ['a/09_new'])
        self.assertIn('excludes no page', result.warnings[0])

    def test_invalid_decks(self):
        for bad in ({'slides': 'a'}, {'pages': []}, ['../x'], ['a/../../x'], [{'title': 'T'}], [3],
                    [{'path': 'a', 'level': 2}], [{'path': 'a', 'duration': 'long'}],
                    [{'path': 'a', 'params': [1]}], ['other:a'],
                    {'sources': {'x': '/does/not/exist'}, 'slides': []}):
            with self.assertRaises(deck.DeckError, msg=repr(bad)):
                deck.load_deck(bad)

    def test_external_source(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ('c/01_u', 'c/02_v'):
                (Path(root) / 'ext' / name).mkdir(parents=True)
                (Path(root) / 'ext' / name / 'index.html.j2').write_text('= u\n')
            loaded = deck.load_deck({'sources': {'ext': 'ext'}, 'slides': ['a/01_x', 'ext:c', '!ext:c/02_v']},
                                    root)
            self.assertEqual(loaded.sources['ext'].mount, 'ext/')
            result = deck.apply_deck(loaded, SLIDES + deck.source_pages(loaded))
            self.assertEqual([deck.page_label(p) for p in result.pages], ['a/01_x', 'ext:c/01_u'])
            # unlisted: local pages only
            self.assertEqual(len(result.unlisted), len(SLIDES) - 1)

    def test_scaffold(self):
        with tempfile.TemporaryDirectory() as root:
            entries = deck.load_deck([{'path': 'a/09_new', 'title': 'New', 'duration': 1}]).entries
            created = deck.scaffold(entries, root)
            self.assertEqual(len(created), 1)
            self.assertEqual(Path(created[0]).read_text(), '= New\n\n::# duration: 1\n')
            Path(created[0]).write_text('= Edited\n')
            self.assertEqual(deck.scaffold(entries, root), [])
            self.assertEqual(Path(created[0]).read_text(), '= Edited\n')


class DeckGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lhtml deck ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name in ('a/01_x', 'a/02_y', 'b/01_w'):
            page = self.root / 'src' / name / 'index.html.j2'
            page.parent.mkdir(parents=True)
            page.write_text(f"{{% set pageTitle = '{name}' %}}\n{{% extends 'theme/template/base.html' %}}\n"
                            f"{{% block content %}}\n= {name}\n{{% endblock %}}\n")
        self.site = self.root / 'site'
        self.config = self.root / 'config.yaml'

    def build(self, deck_value=None, *args):
        config = {'source_directory': 'src', 'site_directory': 'site',
                  'theme': str(REPO / 'themes/slides'), 'plugin': ['plugins/menu.py']}
        if deck_value is not None:
            config['deck'] = deck_value
        self.config.write_text(yaml.safe_dump(config))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(self.config), *args],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return [e['dir'] for e in yaml.safe_load((self.site / 'structure/structure.yaml').read_text())]

    def page_id(self, name):
        html = (self.site / name / 'index.html').read_text()
        return int(html.split('id="current-page-id" class="hidden">')[1].split('<')[0])

    def test_without_deck_file_order(self):
        self.assertEqual(self.build(), ['a/01_x/', 'a/02_y/', 'b/01_w/'])

    def test_deck_file_orders_and_filters(self):
        (self.root / 'deck.yaml').write_text(yaml.safe_dump(
            {'slides': ['b', {'path': 'a/02_y', 'title': 'Y!'}]}))
        self.assertEqual(self.build('deck.yaml'), ['b/01_w/', 'a/02_y/'])
        self.assertEqual(self.page_id('b/01_w'), 0)
        self.assertEqual(self.page_id('a/02_y'), 1)
        self.assertFalse((self.site / 'a/01_x/index.html').exists())
        self.assertFalse((self.site / 'a/01_x/index.html.j2').exists())
        menu = (self.site / 'theme/js/menu.js').read_text()
        self.assertIn('"title": "Y!"', menu)
        # Light mode with another deck given on the command line
        (self.root / 'other.yaml').write_text('slides: [a/01_x]\n')
        self.assertEqual(self.build('deck.yaml', '-l', '--deck', str(self.root / 'other.yaml')), ['a/01_x/'])
        self.assertFalse((self.site / 'b/01_w/index.html').exists())

    def test_scaffold_option(self):
        dirs = self.build([{'path': 'b/02_new', 'title': 'New slide'}, 'b'], '--scaffold')
        self.assertEqual(dirs, ['b/02_new/', 'b/01_w/'])
        self.assertTrue((self.root / 'src/b/02_new/index.html.j2').is_file())

    def test_config_validation(self):
        self.config.write_text('deck: missing.yaml\n')
        with self.assertRaises(ConfigError):
            load_config(self.config)
        self.config.write_text('deck: 3\n')
        with self.assertRaises(ConfigError):
            load_config(self.config)


if __name__ == '__main__':
    unittest.main()


class DeckProjectsTests(unittest.TestCase):
    """Pages of other projects and repeated pages with parameters, end to end."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lhtml deck ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        head = "{% extends 'theme/template/base.html' %}\n{% block content %}\n"
        self.write('talk/src/00_plan/index.html.j2',
                   head + "= Plan\n{% for s in ['A', 'B'] %}"
                   "{% if loop.index == current %}**{{ s }}**{% else %}muted:: {{ s }} ::{% endif %}\n"
                   "{% endfor %}\n{% endblock %}\n")
        self.write('talk/src/01_a/index.html.j2', head + "= A\n{% endblock %}\n")
        self.write('course/src/05_b/01_c/index.html.j2', head + "= C\nimg::assets/c.png\n{% endblock %}\n")
        self.write('course/src/05_b/01_c/assets/c.png', 'png')
        self.write('course/src/05_b/01_c/config.yaml', 'credit: course\n')
        self.write('course/src/05_b/02_d/index.html.j2', head + "= D\n{% endblock %}\n")
        self.site = self.root / 'talk/site'
        self.config = self.root / 'talk/config.yaml'
        self.config.write_text(yaml.safe_dump({
            'source_directory': 'src', 'site_directory': 'site', 'deck': 'deck.yaml',
            'theme': str(REPO / 'themes/slides'), 'plugin': ['plugins/menu.py']}))

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def build(self, deck_data, *args, ok=True):
        (self.root / 'talk/deck.yaml').write_text(yaml.safe_dump(deck_data))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(self.config), *args],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        if ok:
            return yaml.safe_load((self.site / 'structure/structure.yaml').read_text())
        return result.stdout + result.stderr

    DECK = {'sources': {'course': '../course/src'},
            'slides': [{'path': '00_plan', 'params': {'current': 1}}, '01_a', 'course:05_b/01_c',
                       {'path': '00_plan', 'params': {'current': 2}, 'title': 'Plan (2)'}]}

    def test_external_and_repeated_pages(self):
        for args in ((), ('-l',)):
            structure = self.build(self.DECK, *args)
            self.assertEqual([e['dir'] + e['filename'] for e in structure],
                             ['00_plan/index.html', '01_a/index.html', 'course/05_b/01_c/index.html',
                              '00_plan/index-2.html'])
            self.assertEqual(structure[2]['credit'], 'course')
            self.assertEqual(structure[3]['title'], 'Plan (2)')
            first = (self.site / '00_plan/index.html').read_text()
            second = (self.site / '00_plan/index-2.html').read_text()
            self.assertIn('<strong>A</strong>', first)
            self.assertIn('<span class="muted"> B </span>', first)
            self.assertIn('<strong>B</strong>', second)
            self.assertIn('id="current-page-id" class="hidden">3<', second)
            self.assertTrue((self.site / 'course/05_b/01_c/assets/c.png').is_file())
            self.assertIn('../../../theme/css/main.css', (self.site / 'course/05_b/01_c/index.html').read_text())
            self.assertFalse((self.site / 'course/05_b/02_d').exists())

    def test_light_mode_removes_previous_occurrence(self):
        self.build(self.DECK)
        self.build({'slides': ['00_plan', '01_a']}, '-l')
        self.assertFalse((self.site / '00_plan/index-2.html').exists())

    def test_mount_conflict_and_unknown_source(self):
        (self.root / 'talk/src/course').mkdir()
        self.assertIn('already exists', self.build(self.DECK, ok=False))
        self.assertIn("unknown source 'other'", self.build({'slides': ['other:x']}, ok=False))
