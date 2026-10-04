"""Local HTTP preview and polling watcher; no additional runtime dependency."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import os
import threading
import time

from lib import deck
from lib import design
from lib import feedback
from lib.configuration import ConfigError, GENERATOR_DIRECTORY, load_config


def watch_paths(config, filename, deck_arg=None):
    paths = [filename, Path(config.source_directory), Path(config.theme)]
    for plugin in config.plugin:
        candidate = filename.parent / plugin
        paths.append(candidate if candidate.is_file() else GENERATOR_DIRECTORY / plugin)
    for include in config.plugin_arg.get('pre_include', []):
        paths.append(filename.parent / include)
    paths += design.design_files(config.theme, config.design, filename.parent)
    paths += deck.watched_paths(deck.deck_source(deck_arg, config.deck, filename.parent), filename.parent)
    return paths


class PreviewHandler(SimpleHTTPRequestHandler):
    """Serves the site, and the comments on the render (lib/feedback.py) under
    /__feedback/: the script, the comments of a page, new comments, done.

    The comments are only for the pages of this server: every /__feedback/
    request must name it in its Host header (127.0.0.1 or localhost and its
    port: a page of another site whose name leads here, by DNS rebinding,
    does not), and the writes need a custom header and JSON (another site
    cannot send them without a CORS preflight, which is refused)."""
    feedback_directory = None
    MAX_BODY = 100_000

    def log_message(self, format, *args):        # quiet: the build log is enough
        pass

    def _send(self, status, body, content_type='application/json; charset=utf-8'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _local_host(self):
        """Whether the request names this server (Host and, if any, Origin)."""
        port = self.server.server_address[1]
        allowed = {f'{host}:{port}' for host in ('127.0.0.1', 'localhost')}
        if port == 80:
            allowed |= {'127.0.0.1', 'localhost'}
        origin = self.headers.get('Origin')
        return ((self.headers.get('Host') or '').lower() in allowed
                and (not origin or urlsplit(origin).netloc.lower() in allowed))

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path.startswith(feedback.URL) and not self._local_host():
            return self._send(403, '{"error": "forbidden"}')
        if url.path == feedback.URL + 'feedback.js':
            return self._send(200, feedback.SCRIPT.read_bytes(), 'text/javascript; charset=utf-8')
        if url.path == feedback.URL + 'comments':
            page = parse_qs(url.query).get('page', [None])[0]
            try:
                feedback.refresh(self.feedback_directory)       # comments.jsonl edited by hand
                comments = [c for c in feedback.load(self.feedback_directory)
                            if page is None or c.get('page') == page]
            except Exception as exc:
                return self._send(500, json.dumps({'error': str(exc)}))
            return self._send(200, json.dumps(comments, ensure_ascii=False))
        return super().do_GET()

    def do_POST(self):
        url = urlsplit(self.path)
        if (not self._local_host() or self.headers.get('X-Feedback') != '1'
                or not self.headers.get('Content-Type', '').startswith('application/json')):
            return self._send(403, '{"error": "forbidden"}')
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= self.MAX_BODY:
            return self._send(413 if length > 0 else 400, '{"error": "invalid length"}')
        try:
            data = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(data, dict):
                raise feedback.FeedbackError('a JSON object is expected')
            if url.path == feedback.URL + 'comment':
                return self._send(200, json.dumps(feedback.add(self.feedback_directory, data), ensure_ascii=False))
            if url.path == feedback.URL + 'resolve':
                return self._send(200, json.dumps(feedback.resolve(self.feedback_directory, int(data.get('id'))),
                                                  ensure_ascii=False))
        except (ValueError, TypeError, OverflowError) as exc:
            return self._send(400, json.dumps({'error': str(exc)}))
        except Exception as exc:        # always an answer: the browser would send the comment again
            return self._send(500, json.dumps({'error': str(exc)}))
        return self._send(404, '{"error": "not found"}')


def snapshot(paths):
    result = {}
    for path in paths:
        path = Path(path)
        files = [path]
        if path.is_dir():
            files = []
            for directory, dirs, names in os.walk(path):
                dirs[:] = [name for name in dirs if name not in ('.git', '__pycache__')]
                files.extend(Path(directory) / name for name in names)
        for file in files:
            try:
                stat = file.stat()
                result[str(file)] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                result[str(file)] = None
    return result


def develop(args, build):
    filename = Path(args.input_config or 'configure.yaml').expanduser().resolve()
    try:
        config, filename, _ = load_config(filename, args.debug)
    except ConfigError as exc:
        raise SystemExit(str(exc))
    state = {'directory': config.site_directory}
    paths = watch_paths(config, filename, args.deck)
    PreviewHandler.feedback_directory = filename.parent / feedback.DIRECTORY

    def rebuild():
        nonlocal paths
        try:
            fresh, resolved, _ = load_config(filename, args.debug)
            paths = watch_paths(fresh, resolved, args.deck)
            if args.serve:
                try:
                    feedback.refresh(PreviewHandler.feedback_directory)    # comments.jsonl edited by hand
                except Exception as exc:
                    print(f'comments.md not written again: {exc}', flush=True)
            build(args)
            state['directory'] = fresh.site_directory
            print('Build complete.', flush=True)
        except (Exception, SystemExit) as exc:
            print(f'Build failed ({exc}); watching for the next edit. Previous site retained.', flush=True)

    before_build = snapshot(paths)
    rebuild()
    server = None
    thread = None
    if args.serve:

        def handler(*handler_args, **kwargs):
            return PreviewHandler(*handler_args, directory=state['directory'], **kwargs)
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f'Serving http://127.0.0.1:{server.server_port}/ (Ctrl+C to stop); comments on the '
              f'pages (button 💬 or key c) go to {PreviewHandler.feedback_directory}/comments.md', flush=True)
    if args.watch:
        print('Watching sources, theme, plugins and configuration.', flush=True)
    try:
        previous = before_build
        pending = None
        while True:
            time.sleep(0.5)
            if not args.watch:
                continue
            current = snapshot(paths)
            if current == previous:
                pending = None
                continue
            # Require two identical snapshots to avoid building mid-save.
            if current != pending:
                pending = current
                continue
            previous = current
            pending = None
            rebuild()
    except KeyboardInterrupt:
        print('\nPreview stopped.', flush=True)
    finally:
        if server:
            server.shutdown()
            server.server_close()
            thread.join()
