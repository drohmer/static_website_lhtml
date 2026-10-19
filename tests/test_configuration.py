"""Configuration precedence, diagnostics, and non-destructive path validation."""
from pathlib import Path
from types import SimpleNamespace
import os
import re
import subprocess
import sys
import tempfile
import unittest
import yaml

from lhtml_site import deck, design
from lhtml_site.configuration import BuildContext, ConfigError, load_config, validate_paths
from lhtml_site.logger import Logger

REPO = Path(__file__).resolve().parents[1]


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml-config-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / 'src').mkdir()
        self.file = self.root / 'configure.yaml'
        self.write()

    def write(self, **options):
        self.file.write_text(yaml.safe_dump({'source_directory': 'src', **options}))

    def cli(self, *args):
        return subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(self.file), *args],
                              cwd=self.root, capture_output=True, text=True)

    def test_defaults_yaml_cli_and_context_isolation(self):
        self.write(debug=False, keywords={'nested': {'value': 'original'}})
        config, path, _ = load_config(self.file, debug_override=True)
        self.assertTrue(config.debug)
        self.assertEqual(Path(config.site_directory), self.root / '.site')
        context = BuildContext(config, path, SimpleNamespace(), Logger())
        context.meta['keywords']['nested']['value'] = 'changed'
        context.meta['planned_slides'] = ['runtime']
        self.assertEqual(config.keywords['nested']['value'], 'original')
        self.assertTrue(config.title_id)
        self.write(debug=True)
        self.assertTrue(load_config(self.file)[0].debug)
        result = self.cli('--check-config')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('debug: true', result.stdout)
        self.assertIn('debug: false', self.cli('--check-config', '--no-debug').stdout)
        self.write(debug=False)
        self.assertIn('debug: true', self.cli('--check-config', '-d').stdout)

    def test_a_configuration_that_lists_the_layout_report_as_a_plugin_is_refused(self):
        """It is part of the generator now, selected by --layout: a
        configuration of the previous version is told what to change,
        before any build."""
        self.write(plugin=['plugins/generate_pdf.py', 'plugins/layout_report.py'])
        result = self.cli('--check-config', '--layout')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('--layout', result.stdout)
        self.assertFalse((self.root / '.site').exists())

        self.write(plugin=[], plugin_arg={'layout_report': {'root': 'main'}})
        result = self.cli('--check-config')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("'layout:'", ' '.join(result.stdout.split()))

    def test_a_configuration_that_lists_a_core_stage_as_a_plugin_is_refused(self):
        """The menu of the theme and the heading ids are stages of the build:
        a configuration of the previous version is told so, before any build."""
        for entry, expected in (('plugins/menu.py', "theme's menu"),
                                ('plugins/title_submenu.py', 'heading ids')):
            self.write(plugin=[entry])
            result = self.cli('--check-config')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            flat = ' '.join(result.stdout.split())
            self.assertIn(expected, flat)
            self.assertIn(entry, flat)
            self.assertFalse((self.root / '.site').exists())

        # the extra keys of the menu are declared by the theme now
        self.write(plugin=[], plugin_arg={'menu': {'keys': ['duration']}})
        result = self.cli('--check-config')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('theme.yaml', ' '.join(result.stdout.split()))

    def test_bad_types_and_yaml_have_actionable_errors(self):
        for key, value in [('source_directory', None), ('site_directory', 3),
                           ('debug', 'false'),
                           ('keywords', []), ('plugin_arg', []), ('plugin', [42]),
                           ('include_head', 'script'), ('log', 'override')]:
            with self.subTest(key=key, value=value):
                self.write(**{key: value})
                result = self.cli('--check-config')
                self.assertEqual(result.returncode, 1)
                self.assertIn(key, result.stdout)
                self.assertNotIn('Traceback', result.stderr)
        for text in ('false', '[]', 'plugin: [broken'):
            self.file.write_text(text)
            with self.assertRaises(ConfigError):
                load_config(self.file)

    def test_unknown_key_and_removed_keys(self):
        self.write(site_directoy='typo', custom_option=42)
        config, _, warnings = load_config(self.file)
        self.assertNotIn('custom_option', config.to_meta())
        self.assertIn("Unknown configuration key 'site_directoy', ignored. Did you mean 'site_directory'",
                      '\n'.join(warnings))
        for key, fix in (('plugin_post', "under 'plugin'"), ('include_head', '<head>'), ('level_print', '-v')):
            self.write(**{key: []})
            with self.assertRaisesRegex(ConfigError, fix):
                load_config(self.file)

    def test_overlapping_paths_and_symlinks_rejected_before_clean(self):
        marker = self.root / 'src/keep.txt'
        marker.write_text('keep')
        theme = self.root / 'theme'
        theme.mkdir()
        link = self.root / 'alias'
        link.symlink_to(self.root / 'src', target_is_directory=True)
        for output in ('src', '.', 'src/output', 'theme', 'theme/output', 'alias', str(REPO)):
            with self.subTest(output=output):
                self.write(site_directory=output, theme='theme')
                result = self.cli('--clean')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('Unsafe', result.stdout)
                self.assertEqual(marker.read_text(), 'keep')

    def test_check_does_not_create_delete_or_execute_plugins(self):
        site = self.root / '.site'
        site.mkdir()
        marker = site / 'keep.txt'
        marker.write_text('keep')
        plugin = self.root / 'plugin.py'
        plugin.write_text("raise RuntimeError('must not be imported')\n")
        self.write(plugin=['plugin.py'])
        result = self.cli('--check-config', '--clean')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(plugin.as_posix(), result.stdout)
        self.assertEqual(marker.read_text(), 'keep')
        self.write(site_directory='fresh')
        self.assertEqual(self.cli('--check-config').returncode, 0)
        self.assertFalse((self.root / 'fresh').exists())
        self.write(plugin=['missing.py'])
        self.assertEqual(self.cli('--check-config').returncode, 1)
        self.assertEqual(self.cli().returncode, 1)
        self.assertEqual(marker.read_text(), 'keep')

    def test_clean_works_without_source_and_only_removes_output(self):
        self.write(source_directory='missing')
        (self.root / '.site').mkdir()
        unrelated = self.root / 'lib/__pycache__'
        unrelated.mkdir(parents=True)
        self.assertEqual(self.cli('--clean').returncode, 0)
        self.assertFalse((self.root / '.site').exists())
        self.assertTrue(unrelated.exists())

    def test_renamed_example_and_directories_are_refused_with_the_new_name(self):
        self.file.rename(self.root / 'configure_example.yaml')
        with self.assertRaisesRegex(ConfigError, 'configure_example.yaml'):
            load_config(self.root / 'configure_default.yaml')
        self.file = self.root / 'configure.yaml'
        (self.root / 'example').mkdir()
        (self.root / 'themes/webpage-frame').mkdir(parents=True)
        for key, old, new in (('source_directory', 'src_site_example', 'example'),
                              ('theme', 'theme_templates/webpage-frame', 'themes/webpage-frame')):
            self.write(**{key: old})
            with self.assertRaisesRegex(ConfigError, new):
                load_config(self.file)

    def test_init_creates_a_project_that_the_command_builds_in_its_directory(self):
        project = self.root / 'project'
        project.mkdir()
        run = lambda *args: subprocess.run([sys.executable, str(REPO / 'generate.py'), *args],
                                           cwd=project, capture_output=True, text=True)
        missing = run()
        self.assertEqual(missing.returncode, 1)
        self.assertIn('lhtml-site init', missing.stdout + missing.stderr)
        self.assertEqual(run('init', 'mon-site').returncode, 0)
        self.assertTrue((project / 'mon-site/configure.yaml').is_file())
        self.assertNotEqual(run('init', 'mon-site').returncode, 0)  # never over a project
        (project / 'a-file').write_text('')
        over_a_file = run('init', 'a-file')
        self.assertIn('is a file', over_a_file.stderr)
        self.assertNotIn('Traceback', over_a_file.stderr)
        project = project / 'mon-site'                              # the command alone, in the project
        result = run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((project / '.site/01_welcome/index.html').is_file())
        self.assertTrue((project / 'src/01_welcome/assets/diagram.svg').is_file())
        self.assertIn("source_directory: 'src/'", (project / 'configure.yaml').read_text())

    def test_init_with_the_slides_theme_copies_a_slide_starter_that_builds_strictly(self):
        project = self.root / 'my-talk'
        run = lambda *args, cwd=self.root: subprocess.run([sys.executable, str(REPO / 'generate.py'), *args],
                                                          cwd=cwd, capture_output=True, text=True)
        result = run('init', 'my-talk', '--theme', 'slides')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('src/01_title/index.html.j2', result.stdout)     # which file to open
        slides = sorted(p.parent.name for p in (project / 'src').glob('*/index.html.j2'))
        self.assertEqual(slides, ['01_title', '02_text', '03_two_columns', '04_image'])
        result = run('--strict', cwd=project)                            # a warning would fail it
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        image = (project / '.site/04_image/index.html').read_text()
        self.assertIn('assets/diagram.svg', image)
        self.assertIn('layout-side', image)
        self.assertIn('class="cols even"', (project / '.site/03_two_columns/index.html').read_text())

    def test_init_on_a_directory_with_src_writes_only_its_configuration(self):
        project = self.root / 'talk'
        (project / 'src/01_title').mkdir(parents=True)
        (project / 'src/01_title/index.html.j2').write_text('= Hello\n')
        run = lambda *args: subprocess.run([sys.executable, str(REPO / 'generate.py'), *args],
                                           cwd=project, capture_output=True, text=True)
        self.assertNotEqual(run('init', '--theme', 'nope').returncode, 0)
        result = run('init', '--theme', 'slides')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((project / 'example').exists())                # the pages are those of src/
        config = load_config(project / 'configure.yaml')[0]
        self.assertEqual(config.source_directory, project / 'src')
        self.assertEqual(config.theme, REPO / 'src/lhtml_site/themes/slides')
        self.assertIn('exists already', run('init').stderr)            # never over a configuration
        result = run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((project / '.site/01_title/index.html').is_file())

    def test_init_offers_every_theme_of_the_generator(self):
        from lhtml_site.generate import THEMES
        shipped = {p.parent.name for p in (REPO / 'src/lhtml_site/themes').glob('*/theme.yaml')}
        self.assertEqual(set(THEMES), shipped)

    def test_paths_into_a_checkout_find_the_files_of_its_package(self):
        """A project with the generator as a submodule names its themes,
        plugins and example as they were at the root of the repository."""
        (self.root / 'generator').symlink_to(REPO, target_is_directory=True)
        self.write(source_directory='generator/example/', theme='generator/themes/slides/',
                   plugin=['generator/plugins/pre_include.py'])
        config = load_config(self.file)[0]
        self.assertEqual(config.theme, REPO / 'src/lhtml_site/themes/slides')
        self.assertEqual(config.source_directory, REPO / 'src/lhtml_site/example')
        self.write(source_directory='generator/src_site_example/')    # the new name, as the project writes it
        with self.assertRaisesRegex(ConfigError, "renamed '[^']*/generator/example' "):
            load_config(self.file)
        self.write(source_directory='generator/example/', theme='generator/themes/slides/',
                   plugin=['generator/plugins/pre_include.py'])
        result = self.cli('--check-config')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('not found', result.stdout)


    def test_chrome_executable_is_resolved_and_checked(self):
        executable = self.root / 'chrome'
        executable.write_text('#!/bin/sh\n')
        executable.chmod(0o755)
        self.write()                                        # without the key
        self.assertIsNone(load_config(self.file)[0].chrome)
        self.assertNotIn('chrome', load_config(self.file)[0].to_meta())

        self.write(chrome='chrome')                          # relative to the configuration
        config = load_config(self.file)[0]
        self.assertEqual(config.chrome, str(executable))
        self.assertEqual(config.to_meta()['chrome'], str(executable))

        bundle = self.root / 'Chrome.app/Contents/MacOS'     # macOS bundle
        bundle.mkdir(parents=True)
        (bundle / 'Chrome').write_text('#!/bin/sh\n')
        (bundle / 'Chrome').chmod(0o755)
        self.write(chrome='Chrome.app')
        self.assertEqual(load_config(self.file)[0].chrome, str(bundle / 'Chrome'))

        not_executable = self.root / 'plain'
        not_executable.write_text('')
        not_executable.chmod(0o644)
        # Windows has no executable bit: a file found is taken as executable
        for value in ('missing-chrome', '   ', 42) + ((str(not_executable),) if os.name != 'nt' else ()):
            self.write(chrome=value)
            with self.assertRaises(ConfigError):
                load_config(self.file)


class ReservedKeysAndWatchTests(unittest.TestCase):
    def test_every_runtime_key_written_by_the_build_is_reserved(self):
        """A key the generator writes in meta must be in RUNTIME_KEYS: the same
        key written in the YAML is then refused as runtime state, rather than
        taken for a typo."""
        from lhtml_site.configuration import Config, RUNTIME_KEYS
        known = set(Config().to_meta()) | {'cache_video_directory', 'chrome', 'design', 'deck'} | RUNTIME_KEYS
        written = {}
        for file in sorted((REPO / 'src/lhtml_site').rglob('*.py')):     # its code and its plugins
            for match in re.finditer(r"meta\[\s*'([a-z_]+)'\s*\]\s*=(?!=)", file.read_text(encoding='utf-8')):
                written.setdefault(match.group(1), file.name)
        unreserved = {key: name for key, name in written.items() if key not in known}
        self.assertEqual(unreserved, {}, f'add these keys to RUNTIME_KEYS: {unreserved}')

    def test_params_keyword_is_reserved(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'c.yaml'
            (Path(temp) / 'src').mkdir()
            config.write_text(yaml.safe_dump({'source_directory': 'src', 'keywords': {'params': 1}}))
            with self.assertRaises(ConfigError):
                load_config(config)

    def test_watched_paths_of_a_file_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / 'ext/e1').mkdir(parents=True)
            (root / 'ext/e1/index.html.j2').write_text('= E\n')
            paths = deck.watched_paths({'sources': {'x': 'ext'}, 'slides': ['x:e1/index.html', 'x:e1/index']},
                                       root)
            self.assertEqual(paths, [root / 'ext/e1', root / 'ext/e1'])

    def test_design_files_follow_extends(self):
        files = design.design_files(REPO / 'src/lhtml_site/themes/slides-pdf')
        self.assertEqual([f.resolve() for f in files],
                         [(REPO / 'src/lhtml_site/themes/slides-pdf/design.yaml').resolve(),
                          (REPO / 'src/lhtml_site/themes/slides/design.yaml').resolve()])


class ReservedConfigTests(unittest.TestCase):

    def test_page_configuration_cannot_set_structure_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'src/a').mkdir(parents=True)
            (root / 'src/a/index.html.j2').write_text('= A\n')
            (root / 'src/a/config.yaml').write_text('template: wide\n')
            (root / 'c.yaml').write_text(yaml.safe_dump({'source_directory': 'src', 'site_directory': 'site'}))
            result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(root / 'c.yaml')],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('reserved key(s) template', ' '.join((result.stdout + result.stderr).split()))


if __name__ == '__main__':
    unittest.main()


class LoggerTests(unittest.TestCase):
    def test_one_line_per_problem_as_written_never_cut(self):
        from lhtml_site import logger
        long = 'a/' * 80 + 'page.html.j2'
        with logger.console.capture() as captured:
            log = Logger()
            log.warning('path\\ [bold]x[/bold] :fire:', f'{long}:3:5')
            log.error('failed')
            log.detail('a stage')                   # -v only
            with log.stage('Pre-process'):
                pass
        self.assertEqual(captured.get().split('\n'),
                         [f'{long}:3:5: warning: path\\ [bold]x[/bold] :fire:', 'error: failed', ''])
        self.assertEqual(log.counts, {'warning': 1, 'error': 1})

    def test_verbose_shows_the_stages(self):
        from lhtml_site import logger
        with logger.console.capture() as captured:
            with Logger(verbose=True).stage('Pre-process'):
                pass
        self.assertRegex(captured.get(), r'^Pre-process\n  \d+\.\d\ds\n$')


class CheckConfigTests(unittest.TestCase):
    """--check-config answers for what the build will refuse, and it loads no
    plugin to do it (the options live in lhtml_site/layout_options.py)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml-check-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / 'src').mkdir()
        (self.root / 'src/a.html.j2').write_text("{% set pageTitle = 'A' %}\n<h1>A</h1>")

    def check(self, **report):
        config = self.root / 'configure.yaml'
        config.write_text(yaml.safe_dump({'source_directory': 'src', 'site_directory': 'site',
                                          'layout': report}))
        return subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--check-config'],
                              cwd=self.root, capture_output=True, text=True)

    def test_the_options_the_build_refuses_are_refused_here(self):
        for bad in ({'jobs': 'four'}, {'width': 'wide'}, {'images': 'yes'},
                    {'design_rules': 42}, {'output': '../../..'}):
            result = self.check(**bad)
            self.assertEqual(result.returncode, 1, (bad, result.stdout + result.stderr))
        self.assertEqual(self.check(jobs=2).returncode, 0)
        for images in (True, 'render', False):
            self.assertEqual(self.check(images=images).returncode, 0, images)

    def test_images_are_the_render_alone_by_default(self):
        from lhtml_site.layout_options import DEFAULTS
        self.assertEqual(DEFAULTS['images'], 'render')
        self.assertIn('unknown: widht', ' '.join(self.check(widht=10).stdout.split()))
