"""The contract of an extension: content in, content out (lib/extensions.py)."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

REPO = Path(__file__).resolve().parents[1]


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml extensions ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.write('src/a/index.html.j2', '= A\n\nbody of a\n')
        self.write('src/b/index.html.j2', '= B\n\nbody of b\n')

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def build(self, plugin, **options):
        self.write('ext.py', plugin)
        self.write('c.yaml', yaml.safe_dump({'source_directory': 'src', 'site_directory': 'site',
                                             'plugin': ['ext.py'], 'plugin_arg': options}))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', 'c.yaml'],
                                cwd=self.root, capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr

    def html(self, name):
        return (self.root / 'site' / name / 'index.html').read_text()

    def test_each_stage_receives_the_page_and_returns_it(self):
        code, output = self.build(
            "seen = []\n"
            "def prepare(context):\n    seen.append(context.options['word'])\n"
            "def pre_process(text, context):\n    return text + '\\n**' + context.page['title'] + '**\\n'\n"
            "def mid_process(html, context):\n    return html.replace('body', seen[0])\n"
            "def post_process(html, context):\n    return html.replace('<strong>', '<strong class=\"x\">')\n",
            word='text')
        self.assertEqual(code, 0, output)
        self.assertIn('text of a', self.html('a'))
        self.assertIn('<strong class="x">B</strong>', self.html('b'))
        self.assertNotIn('**', (self.root / 'src/a/index.html.j2').read_text())     # the sources untouched

    def test_a_warning_names_the_page_and_a_failure_fails_it(self):
        code, output = self.build(
            "def mid_process(html, context):\n"
            "    if '= B' in html or 'body of b' in html:\n        raise ValueError('no b')\n"
            "    context.warning('look at a')\n    return html\n")
        self.assertEqual(code, 1, output)
        self.assertIn('src/a/index.html.j2: warning: ext.py: look at a', output)
        self.assertIn('src/b/index.html.j2: error: ext.py: mid_process: ValueError: no b', output)

    def test_a_stage_returns_the_text(self):
        code, output = self.build("def pre_process(text, context):\n    pass\n")
        self.assertEqual(code, 1)
        self.assertIn('pre_process returned NoneType, not the text of the page', output)

    def test_the_hooks_of_version_2_are_refused_by_name(self):
        code, output = self.build("def pre_process(meta):\n    pass\n")
        self.assertEqual(code, 1)
        self.assertIn('ext.py: pre_process takes 1 argument(s); an extension defines '
                      'pre_process(text, context) -> text', ' '.join(output.split()))

    def test_pre_include_and_code_include(self):
        self.write('macro.html', '{% macro hello() %}Hello{% endmacro %}')
        self.write('code/lib/f.hpp', 'int foo();\nint bar(int x);\n')
        self.write('src/a/index.html.j2', "= A\n{{ hello() }}\ncode::[c++]\n"
                                          "includeadv::{filepath:'lib/f.hpp', research:'bar'}\ncode::[-]\n"
                                          "code::[c++]\nincludeadv::{filepath:'lib/f.hpp'}\ncode::[-]\n")
        self.write('c.yaml', yaml.safe_dump({'source_directory': 'src', 'site_directory': 'site',
                                             'plugin': ['plugins/pre_include.py', 'plugins/code_include.py'],
                                             'plugin_arg': {'pre_include': ['macro.html']}}))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', 'c.yaml'],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        html = self.html('a')
        self.assertIn('Hello', html)
        self.assertEqual(html.count('bar'), 2)              # the line, then the whole file
        self.assertEqual(html.count('foo'), 1)
        self.assertNotIn('includeadv', html)


if __name__ == '__main__':
    unittest.main()
