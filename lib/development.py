"""Local HTTP preview and polling watcher; no additional runtime dependency."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import threading
import time

from lib.configuration import ConfigError, GENERATOR_DIRECTORY, load_config


def watch_paths(config, filename):
    paths = [filename, Path(config.source_directory), Path(config.theme)]
    for plugin in config.plugin:
        candidate = filename.parent / plugin
        paths.append(candidate if candidate.is_file() else GENERATOR_DIRECTORY / plugin)
    for include in config.plugin_arg.get('pre_include', []):
        paths.append(filename.parent / include)
    return paths


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
    paths = watch_paths(config, filename)

    def rebuild():
        nonlocal paths
        try:
            fresh, resolved, _ = load_config(filename, args.debug)
            paths = watch_paths(fresh, resolved)
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
            return SimpleHTTPRequestHandler(*handler_args, directory=state['directory'], **kwargs)
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f'Serving http://127.0.0.1:{server.server_port}/ (Ctrl+C to stop)', flush=True)
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
