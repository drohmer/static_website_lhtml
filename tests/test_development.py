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
