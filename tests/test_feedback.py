"""Comments on the render (lib/feedback.py, the server of lib/development.py)."""
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
import urllib.error
import urllib.request
import tempfile
from pathlib import Path

from lib import feedback
from lib.development import PreviewHandler


class FeedbackServerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'site').mkdir()
        (self.root / 'site/index.html').write_text('<html><body><h1>T</h1></body></html>')
        PreviewHandler.feedback_directory = self.root / feedback.DIRECTORY
        server = ThreadingHTTPServer(('127.0.0.1', 0), lambda *a, **k: PreviewHandler(
            *a, directory=str(self.root / 'site'), **k))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f'http://127.0.0.1:{server.server_port}'

    def post(self, path, data, headers=None):
        headers = {'Content-Type': 'application/json', 'X-Feedback': '1', **(headers or {})}
        request = urllib.request.Request(self.url + path, json.dumps(data).encode(), headers, method='POST')
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, None

    def get(self, path):
        with urllib.request.urlopen(self.url + path) as response:
            return response.read()

    def test_comment_list_and_done(self):
        status, c = self.post('/__feedback/comment', {'page': '/a/index.html', 'src': 'src/a/index.html.j2:3',
                                                      'block': 'h1 T', 'rect': {'x': 1, 'y': 2, 'w': 3, 'h': 4},
                                                      'comment': 'Bigger title'})
        self.assertEqual((status, c['id'], c['status']), (200, 1, 'open'))
        listed = json.loads(self.get('/__feedback/comments?page=/a/index.html'))
        self.assertEqual([x['comment'] for x in listed], ['Bigger title'])
        self.assertEqual(json.loads(self.get('/__feedback/comments?page=/b.html')), [])
        md = (self.root / '.feedback/comments.md').read_text()
        self.assertIn('`src/a/index.html.j2:3`', md)
        self.assertIn('## Open (1)', md)
        self.assertEqual(self.post('/__feedback/resolve', {'id': 1})[1]['status'], 'done')
        self.assertIn('## Done (1)', (self.root / '.feedback/comments.md').read_text())

    def test_only_the_script_of_the_pages_can_write(self):
        comment = {'page': '/', 'comment': 'x'}
        self.assertEqual(self.post('/__feedback/comment', comment, {'X-Feedback': ''})[0], 403)
        self.assertEqual(self.post('/__feedback/comment', comment, {'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.post('/__feedback/comment', {'page': '/', 'comment': ' '})[0], 400)
        self.assertFalse((self.root / '.feedback/comments.jsonl').exists())

    def test_script_and_site(self):
        self.assertIn(b'__feedback', self.get('/__feedback/feedback.js'))
        self.assertIn(b'<h1>T</h1>', self.get('/index.html'))

    def test_script_tag_in_the_pages(self):
        self.assertEqual(feedback.add_script('<body><p>x</p></body>'),
                         '<body><p>x</p><script src="/__feedback/feedback.js" defer></script></body>')


if __name__ == '__main__':
    unittest.main()
