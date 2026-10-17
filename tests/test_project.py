"""A project of several decks, each built to several targets (lib/project.py)."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

import yaml

from lib import project
from lib.configuration import ConfigError, load_config

REPO = Path(__file__).resolve().parents[1]


class ProjectTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml project ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.file = self.root / 'configure.yaml'
        for deck in ('01_a', '02_b'):
            self.page(f'src/{deck}/01_x/index.html.j2', f'= {deck} x\n')
            self.page(f'src/{deck}/02_y/index.html.j2', f'= {deck} y\n')
        (self.root / 'src/.draft').mkdir()

    def page(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def write(self, **options):
        values = {'source_directory': 'src', 'site_directory': '_site', **options}
        self.file.write_text(yaml.safe_dump(values), encoding='utf-8')

    def config(self, **options):
        self.write(**options)
        return load_config(self.file)[0]

    def build(self, *args):
        return subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(self.file), *args],
                              cwd=self.root, capture_output=True, text=True)


class PlanTests(ProjectTests):

    def test_one_deck_one_target_is_the_site_itself(self):
        config = self.config()
        [build] = project.plan(config)
        self.assertEqual((build.deck, build.target, build.label), (None, None, ''))
        self.assertEqual(build.config, config)

    def test_each_directory_is_a_deck_built_to_each_target(self):
        config = self.config(decks='directories', cache_video_directory='cache',
                             targets={'html': {'theme': 'slides'}, 'pdf': {'theme': 'slides-pdf'}})
        builds = project.plan(config)
        self.assertEqual([(b.deck, b.target) for b in builds],
                         [('01_a', 'html'), ('01_a', 'pdf'), ('02_b', 'html'), ('02_b', 'pdf')])
        first = builds[0].config
        self.assertEqual(first.source_directory, self.root / 'src/01_a')
        self.assertEqual(first.site_directory, self.root / '_site/01_a/html')
        self.assertEqual(first.cache_video_directory, self.root / 'cache/01_a')
        self.assertEqual(first.theme, REPO / 'themes/slides')
        self.assertEqual(builds[1].export_name, '01_a')

    def test_only_names_decks_or_pages_of_a_deck(self):
        config = self.config(decks='directories', targets={'html': {'theme': 'slides'}})
        self.assertEqual([(b.deck, b.only) for b in project.plan(config, only=['02_b'])], [('02_b', None)])
        self.assertEqual([(b.deck, b.only) for b in project.plan(config, only=['01_a/02_y', '01_a/01_x'])],
                         [('01_a', ['02_y', '01_x'])])
        self.assertEqual([(b.deck, b.only) for b in project.plan(config, only=['01_a/02_y', '01_a'])],
                         [('01_a', None)])
        with self.assertRaisesRegex(ConfigError, "no deck '03_c'"):
            project.plan(config, only=['03_c'])

    def test_target_chooses_the_targets(self):
        config = self.config(targets={'html': {'theme': 'slides'}, 'pdf': {'theme': 'slides-pdf'}})
        self.assertEqual([b.target for b in project.plan(config, targets=['pdf'])], ['pdf'])
        self.assertEqual([b.config.site_directory for b in project.plan(config, targets=['html'])],
                         [self.root / '_site/html'])
        with self.assertRaisesRegex(ConfigError, 'unknown target'):
            project.plan(config, targets=['epub'])

    def test_invalid_configurations(self):
        for options, message in (({'decks': 'all'}, "'decks' must be 'directories'"),
                                 ({'targets': []}, "'targets' must map"),
                                 ({'targets': {'html': 'slides'}}, 'expected {theme'),
                                 ({'targets': {'html': {'theme': 'nowhere'}}}, 'theme not found'),
                                 ({'targets': {'html': {'theme': 'slides'}}, 'theme': 'x'}, "'theme' and 'targets'")):
            with self.subTest(options=options):
                with self.assertRaisesRegex(ConfigError, message):
                    self.config(**options)


class BuildTests(ProjectTests):

    def test_two_decks_each_in_their_directory(self):
        self.write(decks='directories', targets={'html': {'theme': 'webpage-frame'}})
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for deck in ('01_a', '02_b'):
            self.assertIn(f'{deck} y', (self.root / f'_site/{deck}/html/02_y/index.html').read_text())
        self.assertFalse((self.root / '_site/.draft').exists())

        (self.root / '_site').joinpath('01_a/html/01_x/index.html').write_text('kept')
        result = self.build('--only', '02_b')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / '_site/01_a/html/01_x/index.html').read_text(), 'kept')

    def test_a_deck_that_fails_does_not_stop_the_others_but_fails_the_command(self):
        self.page('src/01_a/03_z/index.html.j2', '{% invalid %}\n')
        self.write(decks='directories', targets={'html': {'theme': 'webpage-frame'}})
        result = self.build()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue((self.root / '_site/02_b/html/01_x/index.html').is_file())
        self.assertIn('Build failed: deck 01_a target html', ' '.join(result.stdout.split()))

    def test_generate_pdf_is_a_target_now(self):
        self.write(plugin=['plugins/generate_pdf.py'])
        result = self.build('--check-config')
        self.assertEqual(result.returncode, 1)
        self.assertIn('targets: pdf:', ' '.join(result.stdout.split()))

    @unittest.skipUnless(os.environ.get('LHTML_BROWSER_TEST') == '1', 'Set LHTML_BROWSER_TEST=1 for Chrome')
    def test_the_pdf_of_a_deck_lands_in_its_directory(self):
        self.write(decks='directories', targets={'pdf': {'theme': 'slides-pdf'}})
        result = self.build('--only', '01_a')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        deck = self.root / '_site/01_a'
        self.assertTrue((deck / '01_a.pdf').is_file())
        self.assertEqual(sorted(p.name for p in (deck / 'images').iterdir()), ['slide_000.jpg', 'slide_001.jpg'])
        self.assertFalse((deck / 'pdf').exists())       # the intermediate site is not published


if __name__ == '__main__':
    unittest.main()
