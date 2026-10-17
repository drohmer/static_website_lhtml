"""A project of several decks, each built to several targets (lib/project.py)."""
from pathlib import Path
import os
import shutil
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

    def test_a_destination_behind_a_symbolic_link_is_refused(self):
        # .site/01_a/html -> src/01_a: the build would replace the sources
        config = self.config(decks='directories', targets={'html': {'theme': 'slides'}})
        (self.root / '_site/01_a').mkdir(parents=True)
        (self.root / '_site/01_a/html').symlink_to(self.root / 'src/01_a', target_is_directory=True)
        with self.assertRaisesRegex(ConfigError, 'is a symbolic link'):
            project.plan(config)
        result = self.build()
        self.assertEqual(result.returncode, 1)
        self.assertTrue((self.root / 'src/01_a/01_x/index.html.j2').is_file())       # the sources are kept
        (self.root / '_site/01_a/html').unlink()
        shutil.rmtree(self.root / '_site')
        (self.root / '_site').symlink_to(self.root / 'elsewhere', target_is_directory=True)
        (self.root / 'elsewhere').mkdir()
        self.assertEqual(len(project.plan(self.config(decks='directories'))), 2)    # the site itself may be a link

    def test_two_targets_exporting_a_pdf_are_refused(self):
        with self.assertRaisesRegex(ConfigError, 'each exports a PDF to the same place'):
            project.plan(self.config(decks='directories', targets={
                'projector': {'theme': 'slides-pdf'}, 'print': {'theme': 'slides-pdf'}}))

    def test_target_chooses_the_targets(self):
        config = self.config(targets={'html': {'theme': 'slides'}, 'pdf': {'theme': 'slides-pdf'}})
        self.assertEqual([b.target for b in project.plan(config, targets=['pdf'])], ['pdf'])
        self.assertEqual([b.config.site_directory for b in project.plan(config, targets=['html'])],
                         [self.root / '_site/html'])
        with self.assertRaisesRegex(ConfigError, 'unknown target'):
            project.plan(config, targets=['epub'])

    def test_a_deck_with_a_pdf_theme_and_no_targets_renders_in_its_directory(self):
        config = self.config(decks='directories', theme='slides-pdf')
        build = project.plan(config)[0]
        self.assertEqual(build.config.site_directory, self.root / '_site/01_a/pdf')    # PDF in _site/01_a/
        self.assertEqual(build.scope, '01_a')

    def test_no_deck_is_an_error(self):
        for deck in ('01_a', '02_b'):
            for page in (self.root / 'src' / deck).rglob('*.j2'):
                page.unlink()
            for directory in sorted((self.root / 'src' / deck).rglob('*'), reverse=True):
                directory.rmdir()
            (self.root / 'src' / deck).rmdir()
        with self.assertRaisesRegex(ConfigError, 'has no deck'):
            project.plan(self.config(decks='directories'))

    def test_a_theme_of_the_generator_by_its_name(self):
        self.assertEqual(self.config(theme='slides').theme, REPO / 'themes/slides')

    def test_the_target_themes_are_watched(self):
        from lib.development import watch_paths
        config = self.config(targets={'html': {'theme': 'slides'}, 'pdf': {'theme': 'slides-pdf'}})
        paths = watch_paths(config, self.file)
        self.assertIn(REPO / 'themes/slides', paths)
        self.assertIn(REPO / 'themes/slides-pdf', paths)

    def test_invalid_configurations(self):
        for options, message in (({'decks': 'all'}, "'decks' must be 'directories'"),
                                 ({'targets': []}, "'targets' must map"),
                                 ({'targets': {'html': 'slides'}}, 'expected {theme'),
                                 ({'targets': {'html': {'theme': 'nowhere'}}}, 'theme not found'),
                                 ({'targets': {'images': {'theme': 'slides'}}}, "'images' is where"),
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

    def test_each_build_keeps_its_own_state(self):
        self.write(decks='directories', targets={'html': {'theme': 'webpage-frame'}, 'web': {'theme': 'slides'}})
        self.assertEqual(self.build().returncode, 0)
        for scope in ('01_a/html', '01_a/web', '02_b/html', '02_b/web'):
            self.assertTrue((self.root / '.verification' / scope / 'builds.json').is_file(), scope)
            self.assertIn('/01_x/', (self.root / '.structure' / scope / 'credits.md').read_text())
        for _ in range(2):                  # nothing changed: one page each time, in each build
            output = ' '.join(self.build('--only', '01_a/01_x', '-v').stdout.split())
            self.assertEqual(output.count('1 page(s) to render'), 2, output)
            self.assertNotIn('dependent page', output)

    def test_check_config_prints_one_yaml_document_per_build(self):
        self.write(decks='directories', targets={'html': {'theme': 'slides'}})
        result = self.build('--check-config')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        documents = list(yaml.safe_load_all(result.stdout))
        self.assertEqual([d['build'] for d in documents],
                         [{'deck': '01_a', 'target': 'html'}, {'deck': '02_b', 'target': 'html'}])

    def test_names_as_written_and_pages_outside_the_decks_said(self):
        (self.root / 'src/01_a').rename(self.root / 'src/01_A')
        self.page('src/index.html.j2', '= Top\n')
        self.write(decks='directories', targets={'html': {'theme': 'webpage-frame'}})
        output = ' '.join(self.build().stdout.split())
        self.assertIn('deck 01_A target html', output)
        self.assertIn('belong to no deck', output)

    def test_lint_runs_once_per_deck(self):
        self.page('src/01_a/03_z/index.html.j2', '= Z\ndiv::[height:40px;]::\n')
        self.write(decks='directories', targets={'html': {'theme': 'slides'}, 'pdf': {'theme': 'slides-pdf'}})
        output = self.build('--lint').stdout
        self.assertEqual(output.count('03_z/index.html.j2:2'), 1, output)

    def test_a_deck_that_fails_does_not_stop_the_others_but_fails_the_command(self):
        self.page('src/01_a/03_z/index.html.j2', '{% invalid %}\n')
        self.write(decks='directories', targets={'html': {'theme': 'webpage-frame'}})
        result = self.build()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue((self.root / '_site/02_b/html/01_x/index.html').is_file())
        output = ' '.join(result.stdout.split())
        self.assertIn('src/01_a/03_z/index.html.j2:1: error: Jinja: Encountered unknown tag', output)
        self.assertIn('error: deck 01_a target html: build failed (previous site kept): 1 page(s) failed', output)
        self.assertIn('deck 02_b target html: 2 page(s) built in', output)
        self.assertIn('error: 1 of 2 builds failed: deck 01_a target html', output)

    def test_one_line_per_build_and_each_problem_at_its_line(self):
        self.page('src/01_a/01_x/index.html.j2', '---\ntitle: X\n---\n= X\n\ngap::zz\n')
        self.page('src/02_b/01_x/index.html.j2', '= X\n\n{{ missing.field }}\n')
        self.write(decks='directories', targets={'html': {'theme': 'slides'}})
        result = self.build()
        lines = result.stdout.splitlines()
        self.assertIn("src/01_a/01_x/index.html.j2:6:1: warning: gap::zz: unknown variant (expected one of "
                      "s, m, l, xl) near 'gap::zz'", lines)
        self.assertRegex(result.stdout, r'deck 01_a target html: 2 page\(s\) built in \d+\.\ds, '
                                        r'1 warning\(s\) -> _site/01_a/html\n')
        self.assertIn("src/02_b/01_x/index.html.j2:3: error: Jinja: 'missing' is undefined", lines)
        self.assertNotIn('Pre-process', result.stdout)                # the stages: with -v
        self.assertIn('Pre-process', self.build('-v', '--only', '01_a').stdout)

    def test_strict_fails_on_a_warning(self):
        self.page('src/01_a/01_x/index.html.j2', '= X\ngap::zz\n')
        self.write(decks='directories', targets={'html': {'theme': 'slides'}})
        self.assertEqual(self.build('--only', '01_a').returncode, 0)
        before = (self.root / '_site/01_a/html/02_y/index.html').read_text()
        self.page('src/01_a/02_y/index.html.j2', '= New y\n')
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(self.file), '--strict'],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('error: deck 01_a target html: build failed (previous site kept): 1 warning(s) with --strict',
                      result.stdout)
        self.assertEqual((self.root / '_site/01_a/html/02_y/index.html').read_text(), before)   # not published

    def test_strict_counts_the_warnings_of_the_configuration(self):
        self.write(decks='directories', targets={'html': {'theme': 'slides'}}, unknown_key=1)
        result = self.build('--strict')
        self.assertEqual(result.returncode, 1)
        self.assertIn('error: 1 warning(s) with --strict', result.stdout)

    def test_a_jinja_error_names_the_file_it_is_in(self):
        self.page('src/01_a/01_x/index.html.j2', '= X\n\nfirst\n{% include "01_a/02_y/index.html.j2" %}\n')
        self.page('src/01_a/02_y/index.html.j2', '= Y\n\nfirst\n{{ missing_b.x }}\n')
        self.page('src/02_b/01_x/index.html.j2', '= X\n{{ "abc" | nofilter }}\n')
        theme = self.root / 'mytheme'
        import shutil
        shutil.copytree(REPO / 'themes/slides', theme)
        base = theme / 'template/base.html'
        lines = base.read_text().split('\n')
        lines[6] = '{{ nothere.x }}'
        base.write_text('\n'.join(lines))
        self.write(decks='directories', targets={'html': {'theme': 'slides'}})
        output = self.build().stdout
        self.assertIn("src/01_a/02_y/index.html.j2:4: error: Jinja: 'missing_b' is undefined", output)
        self.assertIn("src/02_b/01_x/index.html.j2:2: error: Jinja: No filter named 'nofilter'", output)
        self.assertIn('deck 02_b target html: build failed', output)
        self.page('src/02_b/01_x/index.html.j2', '= X\n')
        self.write(decks='directories', targets={'html': {'theme': 'mytheme'}})
        self.assertIn("mytheme/template/base.html:7: error: Jinja: 'nothere' is undefined", self.build().stdout)

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
        self.assertIn('-> _site/01_a/01_a.pdf', result.stdout)            # what the build made
        deck = self.root / '_site/01_a'
        self.assertTrue((deck / '01_a.pdf').is_file())
        self.assertEqual(sorted(p.name for p in (deck / 'images').iterdir()), ['slide_000.jpg', 'slide_001.jpg'])
        self.assertFalse((deck / 'pdf').exists())       # the intermediate site is not published

        self.assertEqual(self.build('--only', '01_a', '-d').returncode, 0)
        self.assertTrue((deck / 'pdf').is_dir())         # kept by --debug
        for page in (self.root / 'src/01_a/02_y').iterdir():
            page.unlink()
        (self.root / 'src/01_a/02_y').rmdir()
        result = self.build('--only', '01_a')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((deck / 'pdf').exists())        # the stale site goes with the next build
        self.assertEqual(sorted(p.name for p in (deck / 'images').iterdir()), ['slide_000.jpg'])


if __name__ == '__main__':
    unittest.main()
