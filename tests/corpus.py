#!/usr/bin/env python3
"""Fingerprint of a built site, and comparison with a reference (step N0).

Not a test: the corpus is outside this repository (several GB of sources and
videos), so this script is run by hand before and after a step.

    python3 tests/corpus.py snapshot <site_dir> <reference.json>
    python3 tests/corpus.py compare  <reference.json> <site_dir>
    python3 tests/corpus.py pages    <reference.json> <site_dir>
    python3 tests/corpus.py volatile <reference.json> <site_dir>

A fingerprint lists every file of the site with its size and its sha256. The
text files also get a hash of their content once the names a rebuild changes
on its own are masked (MASKS), so a difference there is a difference of the
site, not of the run. `compare` exits with 1 when the two sites differ.

Each page of a PDF is also rendered at low resolution, and the render is
hashed: a missing image, a moved or overlapping block changes it where the
text does not. A page showing a video changes from one build to the next
(the frame captured); `volatile`, given a second build of the same sources,
marks the pages that differ, and `compare` skips them. `pages` adds the
renders to a reference written before they existed, from a site that is
still identical to it.
"""

import hashlib
import json
import platform
import re
import subprocess
import sys
import tempfile
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


PAGE_DPI = 30


def pdf_pages(path):
    """Hash of each page rendered in grey at PAGE_DPI, or None without poppler."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(['pdftoppm', '-r', str(PAGE_DPI), '-gray', str(path), f'{tmp}/p'],
                           capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            return None
        return [sha256(p.read_bytes()) for p in sorted(Path(tmp).iterdir())]


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
            pages = pdf_pages(path)
            if pages is not None:
                entry['pages'] = pages
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
    save(reference, out)
    total = sum(e['size'] for e in reference['files'].values())
    print(f'{len(reference["files"])} files, {total / 1e6:.1f} MB -> {out}')


def differing_pages(before, after):
    """1-based numbers of the pages whose render differs, volatile ones excepted;
    [] when either side has no render or the page counts differ (key says so)."""
    a, b = before.get('pages'), after.get('pages')
    if a is None or b is None or len(a) != len(b):
        return []
    volatile = set(before.get('volatile', []))
    return [k + 1 for k, (x, y) in enumerate(zip(a, b)) if x != y and k + 1 not in volatile]


def load(reference_path):
    return json.loads(Path(reference_path).read_text(encoding='utf-8'))


def save(reference, reference_path):
    Path(reference_path).write_text(json.dumps(reference, indent=1, sort_keys=True) + '\n', encoding='utf-8')


def compare(reference_path, site):
    reference = load(reference_path)
    before, after = reference['files'], fingerprint(Path(site).resolve())
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    common = set(before) & set(after)
    changed = sorted(p for p in common if key(before[p]) != key(after[p]))
    rendered = sorted((p, differing_pages(before[p], after[p])) for p in common if p not in changed)
    rendered = [f'{p}  (pages {", ".join(map(str, pages))})' for p, pages in rendered if pages]
    for title, paths in (('missing', removed), ('new', added), ('changed', changed),
                         ('rendered differently', rendered)):
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
    if removed or added or changed or rendered:
        return 1
    volatile = sum(len(e.get('volatile', [])) for e in before.values())
    print(f'identical: {len(after)} files' + (f' ({volatile} volatile pages skipped)' if volatile else ''))
    return 0


def add_pages(reference_path, site):
    """Adds the renders to a reference, from a site still identical to it."""
    reference = load(reference_path)
    site = Path(site).resolve()
    added = 0
    for rel, entry in reference['files'].items():
        if rel.endswith('.pdf') and 'pages' not in entry:
            path = site / rel
            if not path.is_file() or pdf_key(path) != entry.get('masked'):
                print(f'{rel}: missing or different, no render taken')
                return 1
            entry['pages'] = pdf_pages(path)
            added += 1
    save(reference, reference_path)
    print(f'renders of {added} PDFs -> {reference_path}')
    return 0


def mark_volatile(reference_path, site):
    """Marks the pages a second build of the same sources renders differently."""
    reference = load(reference_path)
    site = Path(site).resolve()
    marked = 0
    for rel, entry in reference['files'].items():
        if 'pages' not in entry or not (site / rel).is_file():
            continue
        pages = differing_pages(entry, {'pages': pdf_pages(site / rel)})
        if pages:
            entry['volatile'] = sorted(set(entry.get('volatile', [])) | set(pages))
            marked += len(pages)
    save(reference, reference_path)
    total = sum(len(e.get('volatile', [])) for e in reference['files'].values())
    print(f'{marked} pages newly volatile, {total} in all -> {reference_path}')
    return 0


def main(argv):
    if len(argv) == 4 and argv[1] == 'snapshot':
        snapshot(argv[2], argv[3])
        return 0
    commands = {'compare': compare, 'pages': add_pages, 'volatile': mark_volatile}
    if len(argv) == 4 and argv[1] in commands:
        return commands[argv[1]](argv[2], argv[3])
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
