"""Comments on the render (lib/feedback.py, the server of lib/development.py)."""
from http.server import ThreadingHTTPServer
import http.client
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

    def raw(self, method, path, body=b'', headers=None):
        """A request with any headers (urllib sets Host and Content-Length itself)."""
        connection = http.client.HTTPConnection('127.0.0.1', int(self.url.rsplit(':', 1)[1]), timeout=5)
        self.addCleanup(connection.close)
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in {'Host': self.url[len('http://'):], 'Content-Type': 'application/json',
                           'X-Feedback': '1', 'Content-Length': str(len(body)), **(headers or {})}.items():
            connection.putheader(key, value)
        connection.endheaders(body)
        return connection.getresponse().status

    def test_other_host_names_are_refused(self):
        """DNS rebinding: a page of another site whose name leads to the server."""
        evil = {'Host': 'evil.example:8765', 'Origin': 'http://evil.example:8765'}
        body = json.dumps({'page': '/', 'comment': 'x'}).encode()
        self.assertEqual(self.raw('POST', '/__feedback/comment', body, evil), 403)
        self.assertEqual(self.raw('GET', '/__feedback/comments', headers={'Host': 'evil.example:8765'}), 403)
        self.assertEqual(self.raw('POST', '/__feedback/comment', body, {'Host': 'localhost:' + self.url.rsplit(':', 1)[1]}), 200)

    def test_malformed_requests(self):
        for body in (b'[1, 2]', b'{"comment": "x", "rect": [1, 2]}', b'{"comment": "x", "rect": {"x": 1e999}}',
                     b'{"id": 1e999}', b'not json'):
            path = '/__feedback/resolve' if b'"id"' in body else '/__feedback/comment'
            self.assertIn(self.raw('POST', path, body), (200, 400, 404), body)
        self.assertEqual(self.raw('POST', '/__feedback/comment', b'{}', {'Content-Length': 'abc'}), 400)
        self.assertEqual(self.raw('POST', '/__feedback/comment', b'', {'Content-Length': '-1'}), 400)
        rects = [c['rect'] for c in feedback.load(self.root / feedback.DIRECTORY)]
        self.assertEqual(rects, [{'x': 0, 'y': 0, 'w': 0, 'h': 0}] * 2)

    def test_comments_md_written_again(self):
        self.post('/__feedback/comment', {'page': '/', 'comment': 'x'})
        directory = self.root / feedback.DIRECTORY
        jsonl = directory / 'comments.jsonl'
        jsonl.write_text(jsonl.read_text().replace('"open"', '"done"'))
        feedback.refresh(directory)
        self.assertIn('## Done (1)', (directory / 'comments.md').read_text())

    def test_script_and_site(self):
        self.assertIn(b'__feedback', self.get('/__feedback/feedback.js'))
        self.assertIn(b'<h1>T</h1>', self.get('/index.html'))

    def test_script_tag_in_the_pages(self):
        self.assertEqual(feedback.add_script('<body><p>x</p></body>'),
                         '<body><p>x</p><script src="/__feedback/feedback.js" defer></script></body>')


if __name__ == '__main__':
    unittest.main()
