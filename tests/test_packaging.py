"""The files the package ships (pyproject.toml, package-data).

The wheel and the sdist are built from a copy of the repository in which a
build was made inside the package (.site/, .structure/, ... as a build of
the example in place leaves them): none of it may be shipped, nor the
heavy demo example/, and the starters of `lhtml-site init` must be.
Needs `build` and setuptools (requirements-dev.txt): skipped without them.
"""
import importlib.util
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = 'lhtml_site'
# What a build leaves in its directory: hidden directories, and the usual
# site, video cache and configuration of a project
BUILD_OUTPUT = re.compile(r'(^|/)(\.[^/]+|_site|cache_video|node_modules)(/|$)|(^|/)configure\.yaml$')
WHEEL_LIMIT = 15_000_000        # bytes; 66 MB before the example and the font formats left


def shipped(names):
    """The paths inside the package, from the names of an archive."""
    return [n.split(PACKAGE + '/', 1)[1] for n in names if PACKAGE + '/' in n]


@unittest.skipUnless(importlib.util.find_spec('build') and importlib.util.find_spec('setuptools'),
                     'needs build and setuptools (pip install -r requirements-dev.txt)')
class PackageContentTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        source = cls.tmp / 'source'
        files = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard'], cwd=REPO,
                               capture_output=True, text=True, check=True).stdout.splitlines()
        for name in files:
            if (REPO / name).is_file():
                (source / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO / name, source / name)
        package = source / 'src' / PACKAGE
        for planted in ('.site/index.html', '.structure/design.md', '.verification/report.md',
                        '.layout/summary.md', '.source-map/a.json', '_site/index.html',
                        'cache_video/a.mp4', 'configure.yaml', 'starters/slides/.site/index.html',
                        'themes/slides/.structure/design.md'):
            (package / planted).parent.mkdir(parents=True, exist_ok=True)
            (package / planted).write_text('build output')
        # a stale egg-info of an earlier build, which still lists the demo (MANIFEST.in prunes it)
        stale = source / 'src' / (PACKAGE + '.egg-info')
        stale.mkdir()
        (stale / 'SOURCES.txt').write_text('\n'.join(n for n in files if '/example/' in n) + '\n')
        result = subprocess.run([sys.executable, '-m', 'build', '--no-isolation', '-o', str(cls.tmp / 'dist'),
                                 str(source)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.wheel = next((cls.tmp / 'dist').glob('*.whl'))
        cls.sdist = next((cls.tmp / 'dist').glob('*.tar.gz'))
        cls.wheel_files = shipped(zipfile.ZipFile(cls.wheel).namelist())
        cls.sdist_files = shipped(tarfile.open(cls.sdist).getnames())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_no_build_output_is_shipped(self):
        for files in (self.wheel_files, self.sdist_files):
            self.assertEqual([f for f in files if BUILD_OUTPUT.search(f)], [])

    def test_the_demo_example_is_not_shipped_and_the_starters_are(self):
        for files in (self.wheel_files, self.sdist_files):
            self.assertEqual([f for f in files if f.startswith('example/')], [])
            for starter in ('starters/slides/01_title/index.html.j2', 'starters/site/01_welcome/index.html.j2',
                            'themes/slides/theme.yaml', 'plugins/assets/chrome.js', 'docs/agents.md',
                            'configure_example.yaml', 'feedback.js'):
                self.assertIn(starter, files)

    def test_the_sdist_has_the_changelog(self):
        names = tarfile.open(self.sdist).getnames()
        self.assertTrue(any(n.endswith('/CHANGELOG.md') for n in names))

    def test_the_wheel_stays_light(self):
        self.assertLess(self.wheel.stat().st_size, WHEEL_LIMIT)


if __name__ == '__main__':
    unittest.main()
