from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from lib import deck
from lib.configuration import ConfigError, load_config
from lib.pages import Page, Source, discover

REPO = Path(__file__).resolve().parents[1]


PROJECT = Source(None, '/project/')


def pages(*paths):
    """Pages of the project in file order, as pages.discover returns them."""
    result = []
    for path in paths:
        directory, _, filename = path.rpartition('/')
        result.append(Page(PROJECT, directory + '/' if directory else '', filename))
    return result


SLIDES = pages('a/00_section/index.html.j2', 'a/01_x/index.html.j2', 'a/02_y/index.html.j2',
               'a/03_todo_z/index.html.j2', 'b/00_section/index.html.j2', 'b/01_w/index.html.j2')


def order(slides, source=SLIDES):
    result = deck.apply_deck(deck.load_deck({'slides': slides}), source)
    return [p.id for p in result.pages], result


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
        self.assertEqual([p.id for p in result.unlisted], ['a/03_todo_z', 'b/00_section', 'b/01_w'])

    def test_metadata(self):
        ids, result = order([{'path': 'a/01_x', 'title': 'X', 'duration': 2}, 'b/01_w/'])
        self.assertEqual(ids, ['a/01_x', 'b/01_w'])
        self.assertEqual(result.pages[0].meta, {'title': 'X', 'duration': 2})
        self.assertEqual(result.duration(), (2, 1))

    def test_listed_and_excluded_warns(self):
        ids, result = order(['a/01_x', 'b', '!a/*'])
        self.assertEqual(ids, ['b/00_section', 'b/01_w'])
        self.assertIn('also excluded', result.warnings[0])

    def test_repeated_pointer_gives_occurrences(self):
        ids, result = order([{'path': 'a/01_x', 'params': {'current': 1}}, 'b',
                             {'path': 'a/01_x', 'params': {'current': 2}}, 'a'])
        self.assertEqual(ids, ['a/01_x', 'b/00_section', 'b/01_w', 'a/01_x',
                               'a/00_section', 'a/02_y', 'a/03_todo_z'])
        self.assertEqual([p.occurrence for p in result.pages[:4]], [1, 1, 1, 2])
        self.assertEqual(result.pages[0].params, {'current': 1})
        self.assertEqual(result.pages[3].params, {'current': 2})
        self.assertEqual(result.warnings, [])

    def test_several_pages_in_a_directory(self):
        site = pages('index.html.j2', 'course/intro.html.j2', 'course/index.html.j2')
        ids, result = order(['course/intro.html', 'index.html', 'course'], site)
        self.assertEqual([p.file for p in result.pages],
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
                    [{'path': 'a', 'params': [1]}],
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
            self.assertEqual(loaded.sources['ext'], str(Path(root, 'ext').resolve()) + '/')
            result = deck.apply_deck(loaded, SLIDES + discover(Source('ext', loaded.sources['ext'])))
            self.assertEqual([p.label for p in result.pages], ['a/01_x', 'ext:c/01_u'])
            self.assertEqual(result.pages[1].site_directory, 'ext/c/01_u/')
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
        self.assertIn('rename the source', self.build(self.DECK, ok=False))
        self.assertIn("no source named", self.build({'slides': ['other:x']}, ok=False))


class DeckRegressionTests(unittest.TestCase):
    """Bugs found by review (one test per bug)."""

    def test_single_page_section_is_moved_not_repeated(self):
        source = pages('a/01_x/index.html.j2', 's/01_only/index.html.j2')
        ids, result = order(['s', 'a', 's/01_only'], source)
        self.assertEqual(ids, ['a/01_x', 's/01_only'])
        self.assertEqual([p.occurrence for p in result.pages], [1, 1])

    def test_duration_of_a_directory_counts_once(self):
        _, result = order([{'path': 'a', 'duration': 3}, {'path': 'b/01_w', 'duration': 1}])
        self.assertEqual(result.duration(), (4, 5))

    def test_label_of_several_pages_in_a_directory(self):
        site = pages('m/index.html.j2', 'm/other.html.j2')
        self.assertEqual([p.label for p in site], ['m', 'm/other.html'])

    def test_source_names(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ('e1', 'src/taken'):
                (Path(root) / name).mkdir(parents=True)
            for name in ('sitemap', 'theme', 'structure'):
                with self.assertRaisesRegex(deck.DeckError, 'directory of the generator'):
                    deck.load_deck({'sources': {name: 'e1'}, 'slides': []}, root)
            loaded = deck.load_deck({'sources': {'taken': 'e1'}, 'slides': []}, root)
            with self.assertRaisesRegex(deck.DeckError, "already has a directory 'taken/'"):
                deck.check_sources(loaded, Path(root) / 'src')
            with self.assertRaises(deck.DeckError):   # mount was removed
                deck.load_deck({'sources': {'a': {'path': 'e1', 'mount': 'x'}}, 'slides': []}, root)

    def test_watched_paths(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'ext/c/d').mkdir(parents=True)
            (Path(root) / 'deck.yaml').write_text("sources: {ext: ext}\nslides: ['ext:c/d', 'ext:c/0*']\n")
            paths = [p.resolve() for p in deck.watched_paths(str(Path(root) / 'deck.yaml'), root)]
            ext = Path(root, 'ext').resolve()
            self.assertEqual(paths[1:], [ext / 'c/d', ext / 'c'])   # pointed directories, not the project
            self.assertEqual(deck.deck_source('deck.yaml', None, root), str((Path(root) / 'deck.yaml').resolve()))
            self.assertEqual(deck.deck_source(None, 'conf.yaml', root), 'conf.yaml')


class DeckBuildRegressionTests(DeckProjectsTests):
    """End-to-end regressions (projects of DeckProjectsTests)."""

    def test_title_with_quotes_and_auto_wrap(self):
        self.write('talk/src/02_raw/index.html.j2', '= Raw\n')
        config = yaml.safe_load(self.config.read_text())
        config['plugin'] = ['plugins/auto_wrap.py', 'plugins/menu.py']
        self.config.write_text(yaml.safe_dump(config))
        title = 'L\'animation d\'un "personnage" {{ x }}'
        structure = self.build({'slides': [{'path': '02_raw', 'title': title}]})
        self.assertEqual(structure[0]['title'], title)
        self.assertIn('<title> L\'animation d\'un "personnage" {{ x }} </title>',
                      (self.site / '02_raw/index.html').read_text())

    def test_scaffold_never_writes_into_a_section(self):
        self.build({'slides': [{'path': 'course_like', 'title': 'Planned'},
                               {'path': '01_a', 'title': 'Existing'}]}, '--scaffold')
        self.assertTrue((self.root / 'talk/src/course_like/index.html.j2').is_file())
        self.write('talk/src/05_sec/01_p/index.html.j2', '= P\n')
        self.build({'slides': [{'path': '05_sec', 'title': 'Section'}]}, '--scaffold')
        self.assertFalse((self.root / 'talk/src/05_sec/index.html.j2').exists())

    def test_occurrence_names_are_stable(self):
        self.write('talk/src/03_m/index.html.j2', '{% extends "theme/template/base.html" %}{% block content %}= M{% endblock %}\n')
        self.write('talk/src/03_m/index-2.html.j2', '{% extends "theme/template/base.html" %}{% block content %}= M2{% endblock %}\n')
        config = yaml.safe_load(self.config.read_text())
        config['debug'] = True
        self.config.write_text(yaml.safe_dump(config))
        d = {'slides': ['03_m/index.html', {'path': '03_m/index.html', 'title': 'again'}, '03_m/index-2.html']}
        expected = ['03_m/index.html', '03_m/index-3.html', '03_m/index-2.html']
        for args in ((), ('-l',), ('-l',), ()):
            structure = self.build(d, *args)
            self.assertEqual([e['dir'] + e['filename'] for e in structure], expected, args)
            self.assertIn('= M2', (self.site / '03_m/index-2.html.j2').read_text())

    def test_light_mode_copies_assets_of_new_external_pages(self):
        self.build({'slides': ['01_a']})
        self.build(self.DECK, '-l')
        self.assertTrue((self.site / 'course/05_b/01_c/assets/c.png').is_file())

    def test_deck_option_relative_to_configuration(self):
        (self.root / 'talk/short.yaml').write_text('slides: [01_a]\n')
        (self.root / 'talk/deck.yaml').write_text('slides: [00_plan]\n')
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(self.config),
                                 '--deck', 'short.yaml'], capture_output=True, text=True, cwd=str(REPO))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        structure = yaml.safe_load((self.site / 'structure/structure.yaml').read_text())
        self.assertEqual([e['dir'] for e in structure], ['01_a/'])

    def test_empty_deck_warns(self):
        (self.root / 'talk/deck.yaml').write_text("slides: ['!*']\n")
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(self.config)],
                                capture_output=True, text=True)
        self.assertIn('no page selected', result.stdout + result.stderr)


class DeckRound2Tests(unittest.TestCase):
    """Second review: one test per bug."""

    def test_directory_with_own_page_and_subpages(self):
        source = pages('sec/index.html.j2', 'sec/s1/index.html.j2', 'sec/s2/index.html.j2', 'z/index.html.j2')
        ids, _ = order(['sec', 'z'], source)
        self.assertEqual(ids, ['sec', 'sec/s1', 'sec/s2', 'z'])
        ids, _ = order(['sec/index.html', 'z'], source)       # the page itself, by its file
        self.assertEqual(ids, ['sec', 'z'])

    def test_unicode_normalization(self):
        import unicodedata
        source = pages(unicodedata.normalize('NFD', '01_été') + '/index.html.j2')
        ids, _ = order([unicodedata.normalize('NFC', '01_été')], source)
        self.assertEqual(len(ids), 1)

    def test_colon_in_local_path(self):
        ids, _ = order(['part:1'], pages('part:1/index.html.j2'))
        self.assertEqual(ids, ['part:1'])

    def test_scaffold_metadata_file_and_jinja(self):
        with tempfile.TemporaryDirectory() as root:
            entries = deck.load_deck([{'path': 'a/09_new', 'title': 'x {{ y }}', 'notes': 'l1\nl2 **b**'},
                                      {'path': 'a/extra.html', 'title': 'Extra'}]).entries
            created = deck.scaffold(entries, root)
            self.assertEqual(Path(created[0]).read_text(),
                             '= {% raw %}x {{ y }}{% endraw %}\n\n::# notes: l1\n::# l2 **b**\n')
            self.assertEqual(created[1], str(Path(root) / 'a/extra.html.j2'))

    def test_source_containing_the_site(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'src').mkdir()
            loaded = deck.load_deck({'sources': {'me': '.'}, 'slides': []}, root)
            with self.assertRaisesRegex(deck.DeckError, 'contains the site'):
                deck.check_sources(loaded, Path(root) / 'src', Path(root) / 'site')


class DeckBuildRound2Tests(DeckProjectsTests):
    def run_generator(self, *args):
        return subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(self.config), *args],
                              capture_output=True, text=True)

    def test_symlinked_directory_is_never_modified(self):
        for name in ('a', 'b'):
            self.write(f'shared/{name}/index.html.j2', '{% extends "theme/template/base.html" %}'
                                                       '{% block content %}= S{% endblock %}\n')
        (self.root / 'talk/src/shared').symlink_to(self.root / 'shared')
        self.build({'slides': ['01_a', 'shared/a']})
        self.assertTrue((self.root / 'shared/a/index.html.j2').is_file())
        self.assertTrue((self.root / 'shared/b/index.html.j2').is_file())
        self.assertFalse((self.root / 'shared/a/index.html').exists())
        self.assertTrue((self.site / 'shared/a/index.html').is_file())

    def test_emoji_and_date(self):
        self.write('talk/src/02_raw/index.html.j2', '= Party 🎉\n')
        config = yaml.safe_load(self.config.read_text())
        config['plugin'] = ['plugins/auto_wrap.py', 'plugins/menu.py']
        self.config.write_text(yaml.safe_dump(config))
        import datetime
        structure = self.build({'slides': ['02_raw', {'path': '01_a', 'title': 'Fête 🎉',
                                                      'date': datetime.date(2026, 10, 4)}]})
        self.assertIn('<title> Party 🎉 </title>', (self.site / '02_raw/index.html').read_text())
        self.assertEqual(structure[1]['title'], 'Fête 🎉')

    def test_sitemap_ids_of_the_project_are_stable(self):
        uses = "{% extends 'theme/template/base.html' %}{% block content %}\n= Plan\n[{{ pathTo_plan }}]{% endblock %}\n"
        self.write('talk/src/00_plan/index.html.j2', uses)
        self.build({'slides': ['00_plan']})
        alone = (self.site / '00_plan/index.html').read_text()
        self.write('course/src/06_p/index.html.j2', "{% extends 'theme/template/base.html' %}"
                                                    "{% block content %}\n= Plan\n{% endblock %}\n")
        self.build({'sources': {'course': '../course/src'},
                    'slides': ['course:06_p', '00_plan', '00_plan']})
        self.assertIn('[../00_plan/index.html]', alone)
        self.assertIn('[../00_plan/index.html]', (self.site / '00_plan/index.html').read_text())

    def test_check_config_reads_the_deck(self):
        (self.root / 'talk/deck.yaml').write_text("sources: {x: ../nowhere}\nslides: []\n")
        result = self.run_generator('--check-config')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('directory not found', result.stdout + result.stderr)
