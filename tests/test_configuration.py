"""Configuration precedence, diagnostics, and non-destructive path validation."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
import yaml

from lib import deck, design
from lib.configuration import BuildContext, ConfigError, load_config, validate_paths
from lib.logger import Logger

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
        self.write(debug=False, level_print=3, keywords={'nested': {'value': 'original'}})
        config, path, _ = load_config(self.file, debug_override=True)
        self.assertTrue(config.debug)
        self.assertEqual(config.level_print, 3)
        self.assertEqual(Path(config.site_directory), self.root / '.site')
        context = BuildContext(config, path, SimpleNamespace(), Logger())
        context.meta['keywords']['nested']['value'] = 'changed'
        context.meta['headings'] = {'runtime': []}
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

    def test_layout_diagnostic_orders_plugin_before_pdf(self):
        self.write(plugin=['plugins/generate_pdf.py', 'plugins/layout_report.py'])
        result = self.cli('--check-config', '--layout')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = yaml.safe_load(result.stdout)
        paths = report['plugin_paths']
        self.assertEqual([Path(path).name for path in paths], ['layout_report.py', 'generate_pdf.py'])
        self.assertFalse((self.root / '.site').exists())
        self.assertFalse((self.root / '_layout').exists())

    def test_bad_types_and_yaml_have_actionable_errors(self):
        for key, value in [('source_directory', None), ('site_directory', 3),
                           ('debug', 'false'), ('level_print', True), ('level_print', -1),
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

    def test_legacy_alias_unknown_key_and_conflict(self):
        self.write(plugin_post=[], site_directoy='typo', custom_option=42)
        config, _, warnings = load_config(self.file)
        self.assertEqual(config.plugin, [])
        self.assertEqual(config.to_meta()['custom_option'], 42)
        self.assertIn('plugin_post', '\n'.join(warnings))
        self.assertIn("Did you mean 'site_directory'", '\n'.join(warnings))
        self.write(plugin=[], plugin_post=[])
        with self.assertRaises(ConfigError):
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
        self.assertIn(str(plugin), result.stdout)
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

    def test_renamed_example_and_legacy_directories(self):
        example = self.root / 'configure_example.yaml'
        self.file.rename(example)
        config, path, warnings = load_config(self.root / 'configure_default.yaml')
        self.assertEqual(path, example)
        self.assertTrue(warnings)
        (self.root / 'example').mkdir()
        (self.root / 'themes/webpage-frame').mkdir(parents=True)
        self.write(source_directory='src_site_example', theme='theme_templates/webpage-frame')
        config, path, warnings = load_config(self.file)
        validate_paths(config, path)
        self.assertEqual(Path(config.source_directory), self.root / 'example')
        self.assertEqual(len(warnings), 2)


class ReservedKeysAndWatchTests(unittest.TestCase):
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
        files = design.design_files(REPO / 'themes/slides-pdf')
        self.assertEqual([f.resolve() for f in files],
                         [(REPO / 'themes/slides-pdf/design.yaml').resolve(),
                          (REPO / 'themes/slides/design.yaml').resolve()])


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
    def test_shown_as_written(self):
        from lib import logger
        with logger.console.capture() as captured:
            log = Logger()
            log.warning('path\\')
            log.keyvalue('a[b]', '[bold]x[/bold]')
            log.keyvalue('info', 'plain')
        text = captured.get()
        self.assertIn('[Warning] path\\\n', text)
        self.assertIn('[a[b]] [bold]x[/bold]', text)
        self.assertIn('plain', text)
        self.assertNotIn('[info]', text)
