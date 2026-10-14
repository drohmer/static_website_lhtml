"""Content fingerprints for build inputs and the exact artifacts measured.

Input scopes are intentionally conservative: page assets and the whole theme
are tracked, including directory membership. Runtime requests add shared files.
External resources are reported as untracked rather than treated as immutable.
"""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, unquote
import hashlib
import json
import os

from lib import design

SCHEMA = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str,
                                     ensure_ascii=False).encode()).hexdigest()


def file_hash(path, cache=None):
    path = Path(path)
    key = str(path.resolve())
    if cache is not None and key in cache:
        return cache[key]
    try:
        with path.open('rb') as stream:
            value = hashlib.file_digest(stream, 'sha256').hexdigest()
    except (FileNotFoundError, IsADirectoryError):
        value = None
    if cache is not None:
        cache[key] = value
    return value


def scope_files(root, kind):
    root = Path(root)
    found = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d != '__pycache__')
        if kind == 'assets':
            dirs[:] = [d for d in dirs if not any((Path(directory) / d).glob('*.html.j2'))]
        for name in sorted(files):
            if name.startswith('.') or (kind == 'assets' and name.endswith('.j2')):
                continue
            found.append(Path(directory) / name)
    return found


def canonical_input(path, meta):
    """A file in a staged/copied site -> its original source, never a staging path."""
    path = Path(path).resolve()
    site = Path(meta['site_directory']).resolve()
    if site not in path.parents:
        return path
    relative = path.relative_to(site)
    if relative.parts[0] == 'theme':
        return Path(meta['theme']).resolve() / Path(*relative.parts[1:])
    roots = meta.get('source_roots', {})
    if relative.parts[0] in roots:
        return Path(roots[relative.parts[0]]) / Path(*relative.parts[1:])
    # Repeated output template names differ from the original template.
    for entry in meta.get('structure', []):
        if entry.get('template') == relative.as_posix():
            return Path(entry['src']).resolve()
    return Path(meta['source_directory']).resolve() / relative


def page_context(page):
    return json.loads(json.dumps({'page': page.site_html, 'source': str(page.src.resolve()),
            'occurrence': page.occurrence, 'params': page.params,
            'settings': page.settings, 'position': page.position}, default=str))


def input_snapshot(meta, entry, extra=()):
    cache = meta.setdefault('_dependency_hash_cache', {})
    files = {}
    def add(path, kind):
        path = canonical_input(path, meta)
        files[str(path)] = {'sha256': file_hash(path, cache), 'kind': kind}
    add(entry['src'], 'source')
    add(Path(entry['src']).parent / 'config.yaml', 'page_config')
    add(meta['config_file'], 'configuration')
    for path in design.design_files(meta['theme'], meta.get('design'), meta['config_directory']):
        add(path, 'design')
    for path in meta.get('plugin_paths', []):
        add(path, 'plugin')
    # Changes to the evaluator invalidate previous measurements too.
    for directory in ('lib', 'plugins') + (('agent',) if meta.get('verify') else ()):
        for path in scope_files(Path(meta['lib_directory']) / directory, 'engine'):
            if path.suffix in ('.py', '.js'):
                add(path, 'engine')
    add(Path(meta['lib_directory']) / 'generate.py', 'engine')
    for path in extra:
        add(path, 'included_or_runtime')
    scopes = []
    for root, kind in ((meta['theme'], 'theme'), (Path(entry['src']).parent, 'assets')):
        members = {str(p.resolve()): file_hash(p, cache) for p in scope_files(root, kind)}
        scopes.append({'root': str(Path(root).resolve()), 'kind': kind, 'members': members})
    name = entry['dir'] + entry['filename']
    context = json.loads(json.dumps(meta.get('dependency_contexts', {}).get(name, {'source': entry['src']}), default=str))
    payload = {'files': files, 'scopes': scopes, 'context': context}
    return {**payload, 'fingerprint': digest(payload)}


def input_changes(snapshot, meta, context):
    """Refresh precisely the scopes and files of a previous manifest."""
    if not snapshot or not snapshot.get('fingerprint'):
        return [{'kind': 'untracked', 'path': None}]
    cache = meta.setdefault('_dependency_hash_cache', {})
    changes = []
    for path, row in snapshot['files'].items():
        if file_hash(path, cache) != row['sha256']:
            changes.append({'path': path, 'kind': row['kind']})
    for scope in snapshot['scopes']:
        members = {str(p.resolve()): file_hash(p, cache) for p in scope_files(scope['root'], scope['kind'])}
        if members != scope['members']:
            changes.append({'path': scope['root'], 'kind': scope['kind']})
    if snapshot['context'] != context:
        changes.append({'path': None, 'kind': 'page_context'})
    return changes


class ResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('img', 'video', 'audio', 'source', 'script', 'iframe', 'object'):
            for key in ('src', 'poster', 'data'):
                if attrs.get(key):
                    self.urls.append(attrs[key])
        if tag == 'link' and attrs.get('href'):
            self.urls.append(attrs['href'])


def local_resource(url, html):
    parsed = urlparse(url)
    if parsed.scheme == 'file':
        return Path(unquote(parsed.path)).resolve()
    if parsed.scheme or parsed.netloc or url.startswith('#'):
        return None
    return (Path(html).parent / unquote(parsed.path)).resolve()


def make_manifest(meta, entry, runtime_urls=()):
    name = entry['dir'] + entry['filename']
    site = Path(meta['site_directory']).resolve()
    html = site / name
    parser = ResourceParser()
    parser.feed(html.read_text(encoding='utf-8'))
    urls = set(parser.urls) | set(runtime_urls)
    inputs = set(meta.get('template_dependencies', {}).get(name, []))
    inputs.update(meta.get('include_dependencies', {}).get(name, []))
    artifacts = {name: file_hash(html)}
    external = []
    for url in sorted(urls):
        resource = local_resource(url, html)
        if resource is None:
            if urlparse(url).scheme in ('http', 'https') or url.startswith('//'):
                external.append(url)
            continue
        if resource == html:
            continue
        original = canonical_input(resource, meta)
        inputs.add(str(original))
        for suffix in ('.py', '.tex'):
            producer = Path(str(original) + suffix)
            if producer.is_file():
                inputs.add(str(producer))
        if site in resource.parents:
            artifacts[resource.relative_to(site).as_posix()] = file_hash(resource)
        else:
            artifacts[str(resource)] = file_hash(resource)
    return {'schema_version': SCHEMA, 'inputs': input_snapshot(meta, entry, inputs),
            'artifacts': artifacts, 'external_resources': external,
            'artifact_fingerprint': digest(artifacts)}


def freshness(manifest, meta, entry):
    if not manifest or manifest.get('schema_version') != SCHEMA:
        return {'status': 'unknown', 'changes': [{'kind': 'untracked', 'path': None}]}
    name = entry['dir'] + entry['filename']
    changes = input_changes(manifest['inputs'], meta, meta['dependency_contexts'].get(name, {}))
    site = Path(meta['site_directory'])
    for relative, expected in manifest['artifacts'].items():
        if file_hash(site / relative) != expected:
            changes.append({'kind': 'artifact', 'path': relative})
    return {'status': 'stale' if changes else 'unknown' if manifest.get('external_resources') else 'current', 'changes': changes,
            'external_resources_untracked': manifest.get('external_resources', [])}


class BuildStore:
    def __init__(self, meta):
        self.path = Path(meta['config_directory']) / '.verification' / 'builds.json'
        try:
            value = json.loads(self.path.read_text())
            self.pages = value.get('pages', {}) if value.get('schema_version') == SCHEMA else {}
        except (OSError, ValueError):
            self.pages = {}

    def expand(self, meta, selected, built):
        requested = set(built)
        affected, global_change = [], False
        for page in selected:
            old = self.pages.get(page.site_html)
            changes = input_changes(old.get('inputs') if old else None, meta, page_context(page))
            if old:
                for relative, expected in old.get('artifacts', {}).items():
                    if file_hash(Path(meta['site_directory']) / relative) != expected:
                        changes.append({'path': relative, 'kind': 'artifact'})
            if changes:
                affected.append(page)
                global_change |= any(c['kind'] in ('configuration', 'theme', 'design', 'plugin', 'engine', 'untracked')
                                     for c in changes)
        meta['dependency_measure'] = [p.site_html for p in selected if p in requested or p in affected]
        if global_change:
            meta['log'].keyvalue('info', '--only: shared inputs changed or untracked; full build', indent_level=1)
            return None
        expanded = [p for p in selected if p in requested or p in affected]
        if len(expanded) > len(built):
            meta['log'].keyvalue('info', f'--only: {len(expanded) - len(built)} dependent page(s) added', indent_level=1)
        return expanded

    def save(self, meta):
        for entry in meta['built']:
            name = entry['dir'] + entry['filename']
            if (Path(meta['site_directory']) / name).is_file():
                self.pages[name] = make_manifest(meta, entry, meta.get('runtime_resources', {}).get(name, []))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'schema_version': SCHEMA, 'pages': self.pages}, indent=1))
        temporary.replace(self.path)

    def refresh_assets(self, meta, built):
        """--only: refresh shared runtime files previously read outside page dirs."""
        import shutil
        site = Path(meta['site_directory']).resolve()
        for page in built:
            previous = self.pages.get(page.site_html, {})
            for relative in previous.get('artifacts', {}):
                target = site / relative
                if relative == page.site_html or site not in target.resolve().parents:
                    continue
                original = canonical_input(target, meta)
                if original.is_file() and original.suffix != '.j2':
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, target)


def refresh_runtime_files(meta, built):
    """Copy newly referenced shared resources during --only, before post plugins.

    Themes are refreshed by full builds. Figure producers are built separately;
    their source outputs must not overwrite the freshly generated artifacts.
    """
    import shutil
    site = Path(meta['site_directory']).resolve()
    for page in built:
        html = site / page.site_html
        if not html.is_file():
            continue
        parser = ResourceParser()
        parser.feed(html.read_text(encoding='utf-8'))
        for url in parser.urls:
            target = local_resource(url, html)
            if target is None or site not in target.parents or target.relative_to(site).parts[0] == 'theme':
                continue
            original = canonical_input(target, meta)
            if original.is_file() and not any(Path(str(original) + s).is_file() for s in ('.py', '.tex')):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, target)
