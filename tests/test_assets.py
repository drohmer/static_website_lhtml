"""Credits, origin, planned figures (lib/credits.py) and figures made from
code (lib/figures.py), end to end."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

from lib import credits, figures
from lib.pages import Page, Source

REPO = Path(__file__).resolve().parents[1]


class CreditsTests(unittest.TestCase):
    def test_page_credits_and_text(self):
        page = Page(Source(None, '/p/'), 'a/', 'index.html.j2',
                    config={'credits': {'assets/x.jpg': {'author': 'A', 'license': 'CC0'},
                                        'assets/y.png': 'Me'}})
        found = credits.page_credits(page)
        self.assertEqual(credits.text(found['assets/x.jpg']), 'A, CC0')
        self.assertEqual(credits.text(found['assets/y.png']), 'Me')
        with self.assertRaises(credits.CreditsError):
            credits.page_credits(Page(Source(None, '/p/'), 'a/', 'index.html.j2',
                                      config={'credits': {'x.jpg': {'licence': 'typo'}}}))
        with self.assertRaises(credits.CreditsError):
            credits.credit_function(page, found)('assets/z.jpg')

    def test_files_used(self):
        text = 'img::assets/a.jpg[width:10px]\nvideoplay::assets/v.mp4\nimg::https://x.org/b.png\n<img src="c.png">\nimg::d.svg'
        self.assertEqual(credits.files_used(text), ['assets/a.jpg', 'assets/v.mp4', 'c.png'])


class AssetsBuildTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml assets ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def build(self):
        self.write('configure.yaml', yaml.safe_dump({'source_directory': 'src', 'site_directory': 'site',
                                                     'theme': str(REPO / 'themes/slides'),
                                                     'plugin': ['plugins/auto_wrap.py']}))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(self.root / 'configure.yaml')],
                                capture_output=True, text=True)
        return result.returncode, ' '.join((result.stdout + result.stderr).split())

    def test_credits_todo_and_figures(self):
        self.write('src/a/index.html.j2', "= A\nimg::assets/x.jpg\ncredit:: {{ credit('assets/x.jpg') }} ::\n"
                                          "img::assets/y.png\nplaceholder:: a walk cycle ::\nimg::assets/s.svg\n")
        self.write('src/a/config.yaml', yaml.safe_dump({'origin': 'course/a', 'credits': {
            'assets/x.jpg': {'author': 'E. Muybridge', 'license': 'public domain'}}}))
        self.write('src/a/assets/s.svg.py', "import sys\nopen(sys.argv[1], 'w').write('<svg xmlns=\"http://www.w3.org/2000/svg\"/>')\n")
        self.write('src/b/index.html.j2', '= Credits\n{% for c in credits %}* {{ c.file }}: {{ c.text }}\n{% endfor %}')
        code, output = self.build()
        self.assertEqual(code, 0, output)
        site = self.root / 'site'
        self.assertIn('E. Muybridge, public domain', (site / 'a/index.html').read_text())
        self.assertIn('assets/x.jpg: E. Muybridge, public domain', (site / 'b/index.html').read_text())
        report = (site / 'structure/credits.md').read_text()
        self.assertIn('| 1 | a/index.html | A | `src/a/index.html.j2` | course/a |', report)
        self.assertIn('- a/index.html: `assets/y.png`', report)                 # without credit
        self.assertIn('src/a/index.html.j2:5` (a/index.html): a walk cycle', (site / 'structure/todo.md').read_text())
        self.assertIn('To do: 1 planned figure(s)', output)
        self.assertTrue((site / 'a/assets/s.svg').is_file())
        self.assertFalse((self.root / 'src/a/assets/s.svg').exists())          # never in the sources
        self.assertIn('Figures: 1 made', output)
        self.assertIn('Figures: 0 made, 1 from the cache', self.build()[1])

    def test_failed_figure_and_missing_credit(self):
        self.write('src/a/index.html.j2', "= A\ncredit:: {{ credit('assets/none.jpg') }} ::\n")
        self.write('src/b/index.html.j2', '= B\n')
        self.write('src/b/assets/bad.png.py', 'raise SystemExit("no data")\n')
        code, output = self.build()
        self.assertNotEqual(code, 0)
        self.assertIn("no credit for 'assets/none.jpg'", output)
        self.assertIn('Figure not made: b/assets/bad.png.py: no data', output)

    @unittest.skipUnless(shutil.which('latex') and shutil.which('dvisvgm'), 'TeX Live')
    def test_tikz_figure(self):
        figure = self.root / 'f'
        figure.mkdir()
        (figure / 'r.svg.tex').write_text('\\documentclass[tikz]{standalone}\\begin{document}'
                                          '\\tikz\\draw[->] (0,0) -- (1,0);\\end{document}\n')
        made, cached, errors = figures.build_figures([figure], self.root / 'cache')
        self.assertEqual((made, cached, errors), (1, 0, []))
        self.assertIn('<path', (figure / 'r.svg').read_text())


if __name__ == '__main__':
    unittest.main()
