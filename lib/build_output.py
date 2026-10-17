"""Publish a completed build while keeping the previous output on failure."""
from contextlib import contextmanager
from pathlib import Path
import os
import shutil
import tempfile
import uuid


def links_out_of(site):
    """The symbolic links of a site that lead out of it: a build that writes
    in the site (--only) would write through them (into the sources)."""
    site = Path(site)
    if not site.is_dir():
        return []
    real = site.resolve()
    found = []
    for directory, dirs, files in os.walk(site):
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink():
                target = path.resolve()
                if target != real and real not in target.parents:
                    found.append((path, target))
    return found


@contextmanager
def staged_site(meta, copy=False):
    """The build in a staging directory, published when it completes.
    `copy`: the staging directory starts as a copy of the site (a partial
    build that must publish nothing if it is refused: --only --strict)."""
    target = Path(meta['site_directory']).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.site-build-', dir=target.parent))
    if copy and target.is_dir():
        shutil.copytree(target, staging, symlinks=True, dirs_exist_ok=True)
    original = meta['site_directory']
    meta['published_site_directory'] = target
    meta['site_directory'] = staging
    try:
        yield
        # A target may publish something else than the site it rendered: the
        # PDF export keeps <deck>.pdf and images/, and asks for the HTML it
        # used as an intermediate not to be published. It says so rather
        # than deleting the directory under whatever runs next. In a project
        # of decks or targets, the directory of the target is its own: a site
        # published there before (--debug keeps it) goes too, it would be
        # stale. A project of one site may have published something else
        # there, which is kept.
        if not meta.get('publish_site', True):
            shutil.rmtree(staging, ignore_errors=True)
            if meta.get('build_scope'):
                shutil.rmtree(target, ignore_errors=True)
        if staging.is_dir():
            backup = target.with_name('.site-backup-' + uuid.uuid4().hex)
            had_target = target.exists()
            if had_target:
                target.rename(backup)
            try:
                staging.rename(target)
            except BaseException:
                if had_target:
                    backup.rename(target)
                raise
            if had_target:
                shutil.rmtree(backup)
    except BaseException:
        if meta['debug'] and staging.exists():
            meta['log'].warning(f'Failed build kept for inspection: {staging}')
        else:
            shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        meta['site_directory'] = original
        meta.pop('published_site_directory', None)
