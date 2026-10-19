"""The PDF export by Playwright (lhtml_site/pdf_export.py).

The unit tests replace the browser; the browser test (LHTML_BROWSER_TEST=1,
with playwright, pypdf and the Chromium of Playwright) exports the slides
starter for real.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from lhtml_site import browser as headless
from lhtml_site import pdf_export
from lhtml_site.logger import Logger

REPO = Path(__file__).resolve().parents[1]
HAS_PYPDF = importlib.util.find_spec('pypdf') is not None


def blank_pdf(path, pages=1):
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=1443.75, height=813.75)
    with open(path, 'wb') as fid:
        writer.write(fid)


class InstallTest(unittest.TestCase):

    def test_without_playwright_it_says_what_to_install(self):
        with patch.object(pdf_export, 'playwright_available', return_value=False), \
                patch('importlib.util.find_spec', return_value=None):
            with self.assertRaisesRegex(RuntimeError, r'playwright install --only-shell chromium'):
                pdf_export.export_playwright([], [])


class ExportTest(unittest.TestCase):
    """export(), the browser replaced by a function writing what it would."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lhtml pdf ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.site = self.root / 'site'
        self.site.mkdir()
        self.meta = {'site_directory': str(self.site), 'debug': False, 'log': Logger(), 'export_name': 'deck',
                     'structure': [{'dir': f'0{i}/', 'filename': 'index.html'} for i in range(3)]}

    def export(self, browser):
        with patch.object(pdf_export, 'export_playwright', side_effect=browser):
            pdf_export.export(self.meta)

    @unittest.skipUnless(HAS_PYPDF, 'pypdf')
    def test_the_pages_are_merged_in_order_with_their_images(self):
        seen = []

        def browser(inputs, stems, chrome=None, done=None):
            seen.extend(inputs)
            for i, stem in enumerate(stems):
                blank_pdf(stem + '.pdf', pages=i + 1)       # a slide that overflows: all its pages
                Path(stem + '.jpg').write_bytes(b'image')
        (self.root / 'images').mkdir()
        (self.root / 'images/slide_009.jpg').write_bytes(b'stale')      # a slide the deck lost
        self.export(browser)
        from pypdf import PdfReader
        self.assertEqual(len(PdfReader(self.root / 'deck.pdf').pages), 1 + 2 + 3)
        self.assertEqual([p.relative_to(self.site).as_posix() for p in seen],
                         ['00/index.html', '01/index.html', '02/index.html'])
        self.assertEqual(sorted(p.name for p in (self.root / 'images').iterdir()),
                         ['slide_000.jpg', 'slide_001.jpg', 'slide_002.jpg'])
        self.assertFalse(self.meta['publish_site'])
        self.assertEqual(self.meta['exported'], self.root / 'deck.pdf')
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith('pdf-export-')], [])

    def test_a_missing_or_empty_deliverable_is_an_error(self):
        for missing in ('slide_001.pdf', 'slide_002.jpg'):
            with self.subTest(missing=missing):
                old = self.root / 'deck.pdf'
                old.write_bytes(b'previous PDF')

                def browser(inputs, stems, chrome=None, done=None):
                    for stem in stems:
                        Path(stem + '.pdf').write_bytes(b'page')
                        Path(stem + '.jpg').write_bytes(b'image')
                    Path(stems[0]).with_name(missing).write_bytes(b'')     # empty: a page never printed
                with self.assertRaisesRegex(RuntimeError, 'not generated: .*' + missing):
                    self.export(browser)
                self.assertEqual(old.read_bytes(), b'previous PDF')        # untouched
                self.assertTrue(self.site.exists())

    def test_a_failure_of_the_browser_keeps_the_previous_export(self):
        old = self.root / 'deck.pdf'
        old.write_bytes(b'previous PDF')

        def browser(inputs, stems, chrome=None, done=None):
            raise RuntimeError('PDF of 01/index.html not made: Timeout 60000ms exceeded')
        with self.assertRaisesRegex(RuntimeError, 'Timeout'):
            self.export(browser)
        self.assertEqual(old.read_bytes(), b'previous PDF')

    def test_the_chrome_of_the_configuration_is_passed(self):
        chosen = []

        def browser(inputs, stems, chrome=None, done=None):
            chosen.append(chrome)
            raise RuntimeError('stop')
        self.meta['chrome'] = '/opt/chrome'
        with self.assertRaises(RuntimeError):
            self.export(browser)
        self.assertEqual(chosen, ['/opt/chrome'])

    def test_each_page_done_advances_the_progress(self):
        advanced = []

        @contextmanager
        def progress(description, total):
            advanced.append(total)
            yield lambda: advanced.append('page')

        def browser(inputs, stems, chrome=None, done=None):
            for stem in stems:
                done()
            raise RuntimeError('stop')
        with patch.object(self.meta['log'], 'progress', progress), self.assertRaises(RuntimeError):
            self.export(browser)
        self.assertEqual(advanced, [3, 'page', 'page', 'page'])


class InstallMessageTest(unittest.TestCase):

    def test_after_pipx_the_commands_need_no_path(self):
        with patch('lhtml_site.doctor.installation', return_value='pipx'):
            said = headless.missing('The PDF export', pdf_export.PDF_MODULES)
        self.assertIn('pipx inject lhtml-site pypdf, then pipx inject --include-apps lhtml-site playwright', said)
        self.assertIn('then playwright install --only-shell chromium', said)


class ProgressTest(unittest.TestCase):

    def test_no_bar_outside_a_terminal(self):
        log = Logger()
        with patch('lhtml_site.logger.console.print') as printed, log.progress('PDF', 2) as done:
            done()
            done()
        printed.assert_not_called()


@unittest.skipUnless(HAS_PYPDF, 'pypdf')
class MergeTest(unittest.TestCase):

    def test_merge_keeps_every_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            parts = [os.path.join(tmp, f'{i}.pdf') for i in range(3)]
            for i, part in enumerate(parts):
                blank_pdf(part, pages=i + 1)
            pdf_export.merge_pypdf(parts, os.path.join(tmp, 'all.pdf'))
            from pypdf import PdfReader
            self.assertEqual(len(PdfReader(os.path.join(tmp, 'all.pdf')).pages), 6)


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chromium')
def test_the_slides_starter_exports_with_playwright(tmp_path):
    pytest.importorskip('playwright')
    pypdf = pytest.importorskip('pypdf')
    project = tmp_path / 'talk'
    generate = [sys.executable, str(REPO / 'generate.py')]
    subprocess.run(generate + ['init', str(project), '--theme', 'slides-pdf'], check=True, capture_output=True)
    result = subprocess.run(generate + ['-v'], cwd=project, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

    slides = sorted(p.relative_to(project / 'src').parts[0] for p in (project / 'src').glob('*/index.html.j2'))
    reader = pypdf.PdfReader(project / 'slides.pdf')
    assert len(reader.pages) == len(slides)
    box = reader.pages[0].mediabox
    assert (round(float(box.width) / 0.75), round(float(box.height) / 0.75)) == \
        (pdf_export.PAGE_WIDTH, pdf_export.PAGE_HEIGHT)
    assert all(page.extract_text().strip() for page in reader.pages)      # no empty slide
    images = sorted((project / 'images').glob('slide_*.jpg'))
    assert [p.name for p in images] == [f'slide_{i:03}.jpg' for i in range(len(slides))]
    with open(images[0], 'rb') as fid:
        header = fid.read(4096)
    assert header[:2] == b'\xff\xd8'                                     # a JPEG
    width = _jpeg_width(images[0])
    assert width == pdf_export.IMAGE_WIDTH
    assert not list(project.glob('pdf-export-*'))                         # no staging left


def _jpeg_width(path):
    """The width of a JPEG, from its SOF marker."""
    data = Path(path).read_bytes()
    i = 2
    while i < len(data):
        marker, size = data[i + 1], int.from_bytes(data[i + 2:i + 4], 'big')
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 7:i + 9], 'big')
        i += 2 + size
    return None


if __name__ == '__main__':
    unittest.main()


READINESS = (REPO / 'src/lhtml_site/themes/slides/js/readiness.js').read_text(encoding='utf-8')


def _browser_export(tmp_path, html, **frames):
    """_export_playwright on one page (and the frames it names), in Chromium."""
    pytest.importorskip('playwright')
    pytest.importorskip('pypdf')
    for name, text in frames.items():
        (tmp_path / name).write_text(text, encoding='utf-8')
    page = tmp_path / 'page.html'
    page.write_text(html, encoding='utf-8')
    stem = str(tmp_path / 'slide_000')
    import asyncio
    asyncio.run(pdf_export._export_playwright([page], [stem], None))
    from pypdf import PdfReader
    return PdfReader(stem + '.pdf').pages[0].extract_text()


BROWSER = pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chromium')


@BROWSER
def test_a_promise_that_never_settles_fails_the_page_in_time(tmp_path):
    # MathJax whose typesetting never ends: the page fails, after the bound, not never
    html = '<html><body>x<script>window.MathJax = {startup: {promise: new Promise(() => {})}};</script></body></html>'
    with patch.object(pdf_export, 'READY_TIMEOUT', 2000):
        with pytest.raises(RuntimeError, match='not ready after 2 s'):
            _browser_export(tmp_path, html)


@BROWSER
def test_the_page_waits_for_its_readiness_promises(tmp_path):
    # a demo that writes its content asynchronously, then says it is ready
    demo = ('<html><body><div id="d">loading</div><script>' + READINESS + '''
        window.__lhtmlReady.optIn();
        window.__lhtmlReady.waitUntil(new Promise(done => setTimeout(() => {
            document.getElementById('d').textContent = 'PREPARED-IN-PAGE'; done(); }, 800)));
        </script></body></html>''')
    assert 'PREPARED-IN-PAGE' in _browser_export(tmp_path, demo)


@BROWSER
def test_a_frame_waits_for_its_readiness_promises(tmp_path):
    frame = ('<html><body><div id="d">loading</div><script>' + READINESS + '''
        window.__lhtmlReady.optIn();
        window.__lhtmlReady.waitUntil(new Promise(done => setTimeout(() => {
            document.getElementById('d').textContent = 'PREPARED-IN-FRAME'; done(); }, 800)));
        </script></body></html>''')
    html = '<html><body><iframe src="demo.html" width="800" height="300"></iframe></body></html>'
    assert 'PREPARED-IN-FRAME' in _browser_export(tmp_path, html, **{'demo.html': frame})


@BROWSER
def test_a_rejected_readiness_promise_fails_the_page(tmp_path):
    demo = ('<html><body>x<script>' + READINESS + '''
        window.__lhtmlReady.waitUntil(Promise.reject('the demo could not load'));
        </script></body></html>''')
    with pytest.raises(RuntimeError, match='the demo could not load'):
        _browser_export(tmp_path, demo)
