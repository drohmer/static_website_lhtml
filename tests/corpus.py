#!/usr/bin/env python3
"""Fingerprint of a built site, and comparison with a reference (step N0).

Not a test: the corpus is outside this repository (several GB of sources and
videos), so this script is run by hand before and after a step.

    python3 tests/corpus.py snapshot <site_dir> <reference.json>
    python3 tests/corpus.py compare  <reference.json> <site_dir>

A fingerprint lists every file of the site with its size and its sha256. The
text files also get a hash of their content once the names a rebuild changes
on its own are masked (MASKS), so a difference there is a difference of the
site, not of the run. `compare` exits with 1 when the two sites differ.
"""

import hashlib
import json
import platform
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

TEXT_SUFFIXES = {'.html', '.htm', '.css', '.js', '.json', '.xml', '.txt', '.md', '.svg', '.yaml'}

# What a rebuild of the same sources changes on its own. Each entry is
# (name, pattern, replacement); the name is printed when a mask applied, so
# a fingerprint says what it ignored.
MASKS = [
    ('staging directory', re.compile(r'\.site-build-[A-Za-z0-9_]{8}'), '.site-build-XXXXXXXX'),
    ('home directory', re.compile(re.escape(str(Path.home()))), '~'),
]


# A render (a PDF, the image of a slide) is not compared byte for byte: it
# carries the time it was written, and the frame of a video at the moment of
# the capture. A PDF is compared on its pages and its text; the image of a
# slide on its presence only.
RENDER_IMAGE = re.compile(r'(^|/)images/slide_\d+\.(jpg|png)$')


def pdf_key(path):
    """Number of pages and extracted text of a PDF, or None without poppler."""
    try:
        info = subprocess.run(['pdfinfo', str(path)], capture_output=True, text=True, check=True).stdout
        text = subprocess.run(['pdftotext', str(path), '-'], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    pages = re.search(r'^Pages:\s+(\d+)', info, re.M)
    return f'pages={pages.group(1) if pages else "?"} text={sha256(text)}'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def masked(text):
    applied = []
    for name, pattern, replacement in MASKS:
        text, n = pattern.subn(replacement, text)
        if n:
            applied.append(name)
    return text, applied


def fingerprint(site):
    files = {}
    for path in sorted(p for p in site.rglob('*') if p.is_file()):
        rel = path.relative_to(site).as_posix()
        if rel.endswith('.DS_Store'):
            continue
        data = path.read_bytes()
        entry = {'size': len(data), 'sha256': sha256(data)}
        if path.suffix.lower() in TEXT_SUFFIXES:
            text, applied = masked(data.decode('utf-8', errors='surrogateescape'))
            entry['masked'] = sha256(text.encode('utf-8', errors='surrogateescape'))
            if applied:
                entry['masks'] = applied
        elif path.suffix.lower() == '.pdf':
            pdf = pdf_key(path)
            if pdf:
                entry['masked'] = pdf
                entry['masks'] = ['render: pages and text']
        elif RENDER_IMAGE.search(rel):
            entry['masked'] = 'render'
            entry['masks'] = ['render: presence']
        files[rel] = entry
    return files


def environment():
    def version(name):
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None
    return {
        'python': platform.python_version(),
        'lhtml-markup': version('lhtml-markup'),
        'Jinja2': version('Jinja2'),
    }


def key(entry):
    """What two builds must agree on: the masked hash for text, the bytes otherwise."""
    return entry.get('masked', entry['sha256'])


def snapshot(site, out):
    site = Path(site).resolve()
    reference = {'site': str(site), 'environment': environment(), 'files': fingerprint(site)}
    Path(out).write_text(json.dumps(reference, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    total = sum(e['size'] for e in reference['files'].values())
    print(f'{len(reference["files"])} files, {total / 1e6:.1f} MB -> {out}')


def compare(reference_path, site):
    reference = json.loads(Path(reference_path).read_text(encoding='utf-8'))
    before, after = reference['files'], fingerprint(Path(site).resolve())
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    changed = sorted(p for p in set(before) & set(after) if key(before[p]) != key(after[p]))
    for title, paths in (('missing', removed), ('new', added), ('changed', changed)):
        if paths:
            print(f'{title}: {len(paths)}')
            for p in paths[:20]:
                pages = ''
                if p in before and p in after and 'pages=' in key(before[p]) + key(after[p]):
                    pages = f'  ({key(before[p]).split()[0]} -> {key(after[p]).split()[0]})'
                print(f'  {p}{pages}')
            if len(paths) > 20:
                print(f'  ... and {len(paths) - 20} more')
    env_now = environment()
    if env_now != reference['environment']:
        print(f'environment differs: reference {reference["environment"]}, now {env_now}')
    if removed or added or changed:
        return 1
    print(f'identical: {len(after)} files')
    return 0


def main(argv):
    if len(argv) == 4 and argv[1] == 'snapshot':
        snapshot(argv[2], argv[3])
        return 0
    if len(argv) == 4 and argv[1] == 'compare':
        return compare(argv[2], argv[3])
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
