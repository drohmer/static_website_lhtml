"""Local HTTP/watch smoke test; requires permission to bind localhost."""
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.request import urlopen
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.environ.get('LHTML_PREVIEW_TEST') != '1', reason='Set LHTML_PREVIEW_TEST=1 for HTTP/watch')
def test_serve_watch_rebuild_and_recover(tmp_path):
    source = tmp_path / 'src'
    source.mkdir()
    page = source / 'index.html.j2'
    page.write_text('<h1>First version</h1>')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': []}))
    output = tmp_path / 'preview.log'
    with output.open('w') as log:
        process = subprocess.Popen([sys.executable, '-u', str(REPO / 'generate.py'), '-i', str(config),
                                    '--serve', '--watch', '--port', '0'], stdout=log, stderr=log)
        try:
            def wait_for(check):
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    assert process.poll() is None, output.read_text()
                    value = check()
                    if value:
                        return value
                    time.sleep(0.1)
                pytest.fail(output.read_text())
            match = wait_for(lambda: re.search(r'Serving (http://127.0.0.1:\d+/)', output.read_text()))
            url = match.group(1)
            def html():
                with urlopen(url, timeout=2) as response:
                    return response.read().decode()
            assert 'First version' in html()
            page.write_text('<h1>Second version</h1>')
            wait_for(lambda: 'Second version' in html())
            page.write_text('{% invalid %}')
            wait_for(lambda: 'previous site preserved' in output.read_text())
            assert 'Second version' in html()
            page.write_text('<h1>Recovered</h1>')
            wait_for(lambda: 'Recovered' in html())
            assert not list(tmp_path.glob('.site-build-*'))
        finally:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def test_preview_files_are_not_cached(tmp_path):
    """The preview asks the browser to check every file again (no-cache); the
    answers of /__feedback/ keep their own no-store."""
    import threading
    from http.server import ThreadingHTTPServer
    from lib.development import PreviewHandler
    (tmp_path / 'menu.js').write_text('const toc = [];')
    server = ThreadingHTTPServer(('127.0.0.1', 0), lambda *a, **k: PreviewHandler(*a, directory=str(tmp_path), **k))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        with urlopen(f'http://127.0.0.1:{port}/menu.js', timeout=2) as response:
            assert response.headers.get_all('Cache-Control') == ['no-cache']
        from urllib.request import Request
        for method in ('GET', 'HEAD'):      # never 304: the dates of the files are rounded to the second
            request = Request(f'http://127.0.0.1:{port}/menu.js', method=method,
                              headers={'If-Modified-Since': 'Fri, 01 Jan 2100 00:00:00 GMT'})
            with urlopen(request, timeout=2) as response:
                assert response.status == 200
        PreviewHandler.feedback_directory = tmp_path / '.feedback'
        with urlopen(f'http://127.0.0.1:{port}/__feedback/comments', timeout=2) as response:
            assert response.headers.get_all('Cache-Control') == ['no-store']
    finally:
        server.shutdown()
        server.server_close()
