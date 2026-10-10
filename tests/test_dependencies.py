from pathlib import Path
from types import SimpleNamespace

from lib import dependencies
from lib.pages import Page, Source


class Log:
    def keyvalue(self, *args, **kwargs):
        pass


def setup(tmp_path):
    source = tmp_path / 'src'
    source.mkdir()
    theme = tmp_path / 'theme'
    theme.mkdir()
    (theme / 'style.css').write_text('body {}')
    site = tmp_path / '.site'
    site.mkdir()
    config = tmp_path / 'configure.yaml'
    config.write_text('source_directory: src')
    meta = {'config_directory': str(tmp_path), 'source_directory': str(source),
            'theme': str(theme), 'site_directory': str(site), 'config_file': str(config),
            'lib_directory': str(Path(__file__).resolve().parents[1]), 'plugin_paths': [],
            'dependency_contexts': {}, 'log': Log()}
    page = Page(Source(None, str(source) + '/'), '', 'a.html.j2')
    page.name = page.template
    page.src.write_text('= Title')
    entry = {'src': str(page.src), 'dir': '', 'filename': 'a.html'}
    (site / 'a.html').write_text('<img src="media.svg">')
    (source / 'media.svg').write_text('<svg/>')
    (site / 'media.svg').write_text('<svg/>')
    meta['dependency_contexts']['a.html'] = dependencies.page_context(page)
    return meta, page, entry


def clear_cache(meta):
    meta.pop('_dependency_hash_cache', None)


def test_content_change_same_size_mtime_and_new_file(tmp_path):
    meta, page, entry = setup(tmp_path)
    manifest = dependencies.make_manifest(meta, entry)
    assert dependencies.freshness(manifest, meta, entry)['status'] == 'current'
    image = Path(meta['source_directory']) / 'media.svg'
    import os
    timestamp = image.stat().st_mtime_ns
    image.write_text('<SVG/>')
    os.utime(image, ns=(timestamp, timestamp))
    clear_cache(meta)
    assert dependencies.freshness(manifest, meta, entry)['status'] == 'stale'
    image.write_text('<svg/>')
    (image.parent / 'new.dat').write_text('data')
    clear_cache(meta)
    assert dependencies.input_changes(manifest['inputs'], meta, dependencies.page_context(page))


def test_included_file_context_and_artifact_changes(tmp_path):
    meta, page, entry = setup(tmp_path)
    shared = tmp_path / 'common.j2'
    shared.write_text('shared')
    meta['template_dependencies'] = {'a.html': [str(shared)]}
    manifest = dependencies.make_manifest(meta, entry)
    shared.write_text('changed')
    clear_cache(meta)
    assert any(c['path'] == str(shared) for c in dependencies.freshness(manifest, meta, entry)['changes'])
    shared.write_text('shared')
    clear_cache(meta)
    meta['dependency_contexts']['a.html']['params'] = {'step': 2}
    assert any(c['kind'] == 'page_context' for c in dependencies.freshness(manifest, meta, entry)['changes'])
    meta['dependency_contexts']['a.html'] = dependencies.page_context(page)
    (Path(meta['site_directory']) / 'media.svg').write_text('different artifact')
    clear_cache(meta)
    assert any(c['kind'] == 'artifact' for c in dependencies.freshness(manifest, meta, entry)['changes'])


def test_rebuild_selection_and_shared_asset_refresh(tmp_path):
    meta, a, entry = setup(tmp_path)
    b = Page(a.source, '', 'b.html.j2')
    b.name = b.template
    b.src.write_text('= B')
    meta['dependency_contexts']['b.html'] = dependencies.page_context(b)
    (Path(meta['site_directory']) / 'b.html').write_text('B')
    shared = tmp_path / 'shared.lhtml'
    shared.write_text('old')
    meta['template_dependencies'] = {'a.html': [str(shared)]}
    store = dependencies.BuildStore(meta)
    store.pages = {'a.html': dependencies.make_manifest(meta, entry),
                   'b.html': dependencies.make_manifest(meta, {'src': str(b.src), 'dir': '', 'filename': 'b.html'})}
    shared.write_text('new')
    clear_cache(meta)
    assert store.expand(meta, [a, b], [b]) == [a, b]
    (Path(meta['theme']) / 'style.css').write_text('body {color:red}')
    clear_cache(meta)
    assert store.expand(meta, [a, b], [b]) is None


def test_staging_paths_and_external_unknown(tmp_path):
    meta, page, entry = setup(tmp_path)
    (Path(meta['site_directory']) / 'a.html').write_text('<img src="https://example.com/a.png">')
    manifest = dependencies.make_manifest(meta, entry)
    assert dependencies.freshness(manifest, meta, entry)['status'] == 'unknown'
    assert not any('.site/' in key for key in manifest['inputs']['files'])
