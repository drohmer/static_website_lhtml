"""The transcoded variants of the videos, and the contract with LHTML.

LHTML writes a `<source>` per entry that the generator's resolver lists
(lib/video_cache.media); it probes no file itself. These tests pin that
contract, with the variants already in place, so they need no transcoder
installed.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

import lhtml

from lib.video_cache import CACHE_VIDEO_DIR, media

REPO = Path(__file__).resolve().parents[1]


class VideoCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml-video-cache-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        assets = self.root / 'src/a/assets'
        assets.mkdir(parents=True)
        (assets / 'clip.mp4').write_bytes(b'not a real video')
        (self.root / 'src/a/index.html.j2').write_text('= A\n\nvideo::assets/clip.mp4\n')

    def build(self, **options):
        config = self.root / 'configure.yaml'
        config.write_text(yaml.safe_dump({
            'source_directory': 'src', 'site_directory': 'out',
            'theme': str(REPO / 'themes/webpage-frame'), **options}))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return (self.root / 'out/a/index.html').read_text()

    def test_a_project_that_asks_for_nothing_pays_nothing(self):
        """No cache_video_directory: no transcoding, no directory, and the
        page keeps the one source it was written with."""
        html = self.build()
        self.assertEqual(html.count('<source'), 1)
        self.assertIn('clip.mp4', html)
        self.assertFalse((self.root / 'cache_video_directory').exists())

    def test_the_variants_in_the_cache_become_sources_of_the_video(self):
        """What the stage copies into the site is what LHTML then finds."""
        cache = self.root / 'cache' / 'a/assets' / CACHE_VIDEO_DIR
        cache.mkdir(parents=True)
        (cache / 'clip-h264.mp4').write_bytes(b'h264')
        (cache / 'clip-vp9.webm').write_bytes(b'vp9')
        html = self.build(cache_video_directory=str(self.root / 'cache'))
        self.assertIn('clip-h264.mp4', html)
        self.assertIn('clip-vp9.webm', html)
        self.assertIn('type="video/webm"', html)
        # the variants are published next to the video they replace
        copied = self.root / 'out/a/assets' / CACHE_VIDEO_DIR
        self.assertTrue((copied / 'clip-vp9.webm').is_file())

    def test_without_the_converter_a_video_is_shown_as_written(self):
        import os
        env = {**os.environ, 'PATH': os.path.dirname(sys.executable)}       # no ffpb on it
        config = self.root / 'configure.yaml'
        config.write_text(yaml.safe_dump({'source_directory': 'src', 'site_directory': 'out',
                                          'cache_video_directory': 'cache'}))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config)],
                                cwd=self.root, capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('warning: ffpb not found: 1 video(s) not transcoded, shown as written', result.stdout)
        self.assertIn('<source src="assets/clip.mp4"', (self.root / 'out/a/index.html').read_text())

    def test_a_configuration_that_lists_the_plugin_is_refused(self):
        config = self.root / 'old.yaml'
        config.write_text(yaml.safe_dump({
            'source_directory': 'src', 'site_directory': 'old',
            'plugin': ['plugins/cache_video.py']}))
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('cache_video_directory', ' '.join(result.stdout.split()))


class MediaResolverTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='lhtml-media-')
        self.addCleanup(temp.cleanup)
        self.page = Path(temp.name)
        self.variants = self.page / 'assets' / CACHE_VIDEO_DIR
        self.variants.mkdir(parents=True)

    def test_variants_listed_in_the_order_the_browser_tries_them(self):
        for suffix in ('-h264.mp4', '-vp9.webm'):
            (self.variants / f'clip{suffix}').write_bytes(b'')
        self.assertEqual(media(str(self.page))('assets/clip.mp4'), [
            ('assets/cache_video_codecs/clip-vp9.webm', 'video/webm'),
            ('assets/cache_video_codecs/clip-h264.mp4', 'video/mp4')])

    def test_no_variant_keeps_the_source_as_written(self):
        html = lhtml.run('video::assets/clip.mp4\n', {'media': media(str(self.page))})
        self.assertIn('<source src="assets/clip.mp4" type="video/mp4">', html)

    def test_only_a_video_of_an_assets_directory_has_variants(self):
        (self.page / 'other' / CACHE_VIDEO_DIR).mkdir(parents=True)
        (self.page / 'other' / CACHE_VIDEO_DIR / 'clip-h264.mp4').write_bytes(b'')
        self.assertEqual(media(str(self.page))('other/clip.mp4'), [])


class ConverterTests(unittest.TestCase):
    def test_paths_are_accepted(self):
        """The site directory is a Path: the command printed and run takes it."""
        from unittest.mock import patch
        from pathlib import Path
        from lib.video_convert import video_convert
        with patch.object(video_convert.subprocess, 'run') as run:
            video_convert.run(['ffmpeg', '-i', Path('/site/a b.mp4'), 'out.webm'])
        run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
