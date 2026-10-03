"""Publish a completed build while keeping the previous output on failure."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile
import uuid


@contextmanager
def staged_site(meta):
    target = Path(meta['site_directory']).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.site-build-', dir=target.parent))
    original = meta['site_directory']
    meta['published_site_directory'] = str(target) + '/'
    meta['site_directory'] = str(staging) + '/'
    try:
        if meta['args'].light and target.is_dir():
            shutil.copytree(target, staging, dirs_exist_ok=True, symlinks=True)
        yield
        # PDF-only exports may intentionally remove their staging site.
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
