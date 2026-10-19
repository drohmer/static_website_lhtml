"""lhtml-site doctor, and the helpers the build shares with it (lhtml_site/doctor.py)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lhtml_site import doctor

REPO = Path(__file__).resolve().parents[1]


class InstallHintTest(unittest.TestCase):

    def test_after_pipx_a_python_package_is_injected_into_its_environment(self):
        with patch.object(doctor, 'installation', return_value='pipx'):
            self.assertEqual(doctor.install_hint('matplotlib numpy'), 'pipx inject lhtml-site matplotlib numpy')
            self.assertEqual(doctor.install_hint('ffpb', command=True), 'pipx inject --include-apps lhtml-site ffpb')

    def test_otherwise_it_goes_into_the_python_that_runs_the_generator(self):
        with patch.object(doctor, 'installation', return_value='pip'):
            self.assertEqual(doctor.install_hint('libsass'), f'{sys.executable} -m pip install libsass')

    def test_this_checkout_is_seen_as_one(self):
        self.assertEqual(doctor.installation(), 'checkout')


class LookupTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_a_command_next_to_the_python_is_found_without_the_path(self):
        command = self.tmp / 'lhtml-test-command'
        command.write_text('#!/bin/sh\n')
        command.chmod(0o755)
        with patch.object(doctor.sys, 'executable', str(self.tmp / 'python')), \
                patch.dict(os.environ, {'PATH': os.devnull}):
            self.assertEqual(doctor.find_command('lhtml-test-command'), str(command))
            self.assertIsNone(doctor.find_command('lhtml-no-such-command'))

    def test_the_node_modules_of_the_generator_complete_node_path(self):
        modules = self.tmp / 'node_modules'
        with patch.object(doctor, 'NODE_MODULES', modules), patch.dict(os.environ, {'NODE_PATH': '/mine'}):
            self.assertEqual(doctor.node_environment()['NODE_PATH'], '/mine')       # none there yet
            modules.mkdir()
            self.assertEqual(doctor.node_environment()['NODE_PATH'], os.pathsep.join(['/mine', str(modules)]))


class CommandTest(unittest.TestCase):

    def run_doctor(self, env=None):
        return subprocess.run([sys.executable, str(REPO / 'generate.py'), 'doctor'], capture_output=True,
                              text=True, env=env, cwd=tempfile.gettempdir())

    def test_it_lists_every_feature_and_changes_nothing(self):
        result = self.run_doctor()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for feature in ('HTML pages and slides', 'PDF export', 'Layout report', 'Videos in several codecs',
                        'SASS', 'Figures in code', 'Code of other repositories'):
            self.assertIn(feature, result.stdout)

    def test_without_node_it_says_what_to_install_for_the_pdf_export(self):
        env = {**os.environ, 'PATH': os.path.dirname(sys.executable)}       # no node, no poppler
        result = self.run_doctor(env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PDF export with Node (the fallback: LHTML_PDF_ENGINE=node): missing node', result.stdout)
        self.assertRegex(result.stdout, r'missing  puppeteer  -> npm ci')     # a checkout: its package.json
        self.assertRegex(result.stdout, r'missing  pdfunite   -> poppler')


if __name__ == '__main__':
    unittest.main()
