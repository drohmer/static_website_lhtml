"""Copies of the sources into the site (lib/filesystem.py): links."""
from pathlib import Path
import os
import tempfile
import unittest

from lib import filesystem


class CopyTreeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml copy ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def write(self, name, text='x'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_relative_link_in_a_linked_directory_still_resolves(self):
        self.write('ext/img/logo.png', 'logo')
        (self.root / 'ext/common').mkdir(parents=True)
        os.symlink('../img/logo.png', self.root / 'ext/common/logo.png')
        self.write('src/a.txt')
        os.symlink('../ext/common', self.root / 'src/shared')
        os.symlink('a.txt', self.root / 'src/b.txt')
        filesystem.copy_directories(self.root / 'src', self.root / 'site')
        self.assertFalse((self.root / 'site/shared').is_symlink())
        self.assertEqual((self.root / 'site/shared/logo.png').read_text(), 'logo')
        self.assertEqual(os.readlink(self.root / 'site/b.txt'), 'a.txt')    # stays relative

    def test_link_to_the_site_and_to_an_ancestor(self):
        self.write('src/a.txt')
        self.write('_site/html/index.html')
        os.symlink('../_site', self.root / 'src/out')
        (self.root / 'src/b').mkdir()
        os.symlink('..', self.root / 'src/b/parent')
        os.symlink(str(self.root / 'src'), self.root / 'src/absolute')
        staging = self.root / '_site/.site-build-1'
        warnings = filesystem.copy_directories(self.root / 'src', staging,
                                               exclude=[self.root / '_site/html'])
        self.assertEqual(sorted(os.listdir(staging / 'out')), [])       # neither the site nor the copy
        self.assertEqual(os.readlink(staging / 'b/parent'), '..')
        self.assertFalse((staging / 'absolute').exists())
        self.assertEqual(len(warnings), 1)


if __name__ == '__main__':
    unittest.main()
