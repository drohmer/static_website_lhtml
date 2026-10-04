"""Figures defined in code, made at the build.

A file `<name>.<format>.py` of the sources (e.g. `assets/rotation.svg.py`)
is a script that writes the figure `<name>.<format>` (rotation.svg): it gets
the path to write as its argument and runs in its directory (copied into the
site: it can read the files next to it, it never writes into the sources).
`<name>.svg.tex` is a standalone LaTeX document (TikZ...) made into SVG with
latex and dvisvgm. The page uses the figure as any other: `img::assets/rotation.svg`.

The figures are made in the site, after the copy of the sources, and kept in
a cache (.figures/ next to the configuration) under the hash of their
script: a figure is made again only when its script changes (delete .figures/
to make them all again, e.g. after a change of the data they read).
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT_FORMATS = ('svg', 'png', 'pdf', 'jpg')
CACHE = '.figures'
TIMEOUT = 120


def figure_sources(directory):
    """Scripts of figures under a directory (in the site): [(script, figure)]."""
    found = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for name in sorted(files):
            stem, _, kind = name.rpartition('.')
            figure_name, _, fmt = stem.rpartition('.')
            if figure_name and ((kind == 'py' and fmt in SCRIPT_FORMATS) or (kind == 'tex' and fmt == 'svg')):
                found.append((Path(root) / name, Path(root) / stem))
    return found


def _make(script, figure):
    """Make a figure from its script; returns the error text, or None."""
    if script.suffix == '.py':
        result = subprocess.run([sys.executable, script.name, figure.name], cwd=script.parent,
                                capture_output=True, text=True, timeout=TIMEOUT)
        if result.returncode or not figure.is_file():
            return (result.stderr or result.stdout).strip()[-800:] or 'no figure written'
        return None
    if not (shutil.which('latex') and shutil.which('dvisvgm')):
        return 'latex and dvisvgm are needed for the .svg.tex figures (TeX Live)'
    with tempfile.TemporaryDirectory() as build:
        # TikZ draws for dvisvgm (its default driver writes dvips specials)
        result = subprocess.run(['latex', '-interaction=nonstopmode', '-halt-on-error',
                                 f'-output-directory={build}', f'-jobname={script.stem}',
                                 r'\def\pgfsysdriver{pgfsys-dvisvgm.def}\input{' + script.name + '}'],
                                cwd=script.parent, capture_output=True, text=True, timeout=TIMEOUT)
        dvi = Path(build) / (script.stem + '.dvi')         # job name: schema.svg
        if result.returncode or not dvi.is_file():
            return result.stdout.strip()[-800:]
        result = subprocess.run(['dvisvgm', '--no-fonts', '--exact', '-o', str(figure), str(dvi)],
                                capture_output=True, text=True, timeout=TIMEOUT)
        if result.returncode or not figure.is_file():
            return result.stderr.strip()[-800:]
    return None


def build_figures(directories, cache_directory):
    """Make the figures of the scripts under `directories` (in the site), from
    the cache when their script did not change. Returns (made, cached, errors)
    where errors is [(script, message)]."""
    cache = Path(cache_directory)
    made, cached, errors = 0, 0, []
    for directory in directories:
        for script, figure in figure_sources(directory):
            key = hashlib.sha256(script.read_bytes()).hexdigest()[:16]
            kept = cache / f'{key}{figure.suffix}'
            if kept.is_file():
                shutil.copy2(kept, figure)
                cached += 1
                continue
            try:
                error = _make(script, figure)
            except (OSError, subprocess.TimeoutExpired) as exc:
                error = str(exc)
            if error:
                errors.append((script, error))
                continue
            cache.mkdir(parents=True, exist_ok=True)
            shutil.copy2(figure, kept)
            made += 1
    return made, cached, errors
