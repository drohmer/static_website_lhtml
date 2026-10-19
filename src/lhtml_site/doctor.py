"""lhtml-site doctor: what is present and what is missing, feature by feature.

A site of HTML pages or slides needs nothing more than the package. Each
optional feature needs its own programs (Playwright and its Chromium for
the PDF export and the layout report, ffmpeg for the videos, ...): this
command says, for each, what it found and how to install what it did not, for the way the
generator is installed (a checkout, pipx, a virtual environment). It changes
nothing.

The helpers of this module are also those of the build, so that the build
and the diagnosis look for the same things in the same places:
`find_command`, `install_hint`.
"""
import argparse
import importlib.metadata
import importlib.util
import os
import re
import shutil
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def installation():
    """How the generator is installed: 'checkout' (a clone, generate.py next
    to src/), 'pipx', or 'pip' (a virtual environment or another Python)."""
    if (PACKAGE.parents[1] / 'generate.py').is_file():
        return 'checkout'
    if re.search(r'pipx[/\\]venvs', sys.prefix):
        return 'pipx'
    return 'pip'


def install_hint(name, command=False):
    """The command that installs the Python package `name` into the Python
    that runs the generator. After pipx, `pip install` reaches another
    Python: the package goes into the environment of pipx (and a command
    of it, `command=True`, onto its PATH)."""
    if installation() == 'pipx':
        return f"pipx inject {'--include-apps ' if command else ''}lhtml-site {name}"
    return f'{sys.executable} -m pip install {name}'


def find_command(name):
    """A program on the PATH, or next to the Python that runs the generator
    (a command installed with it, by pip or `pipx inject`); None if neither."""
    return shutil.which(name) or shutil.which(name, path=os.path.dirname(sys.executable))


# ---------------------------------------------------------------------------
# The checks: (name, what was found or None, how to install it)
# ---------------------------------------------------------------------------

SYSTEM = {   # program: (what provides it, macOS, Debian/Ubuntu)
    'ffmpeg': ('ffmpeg', 'brew install ffmpeg', 'sudo apt install ffmpeg'),
    'git': ('git', 'xcode-select --install', 'sudo apt install git'),
    'latex': ('TeX Live', 'brew install --cask mactex-no-gui', 'sudo apt install texlive-latex-extra'),
    'dvisvgm': ('TeX Live', 'brew install --cask mactex-no-gui', 'sudo apt install dvisvgm'),
}


def system_check(name):
    provider, mac, linux = SYSTEM[name]
    hint = mac if sys.platform == 'darwin' else linux if sys.platform.startswith('linux') else provider
    return name, find_command(name), f'{provider}: {hint}'


def module_check(module, package=None):
    found = importlib.util.find_spec(module)
    return package or module, found and (found.origin or module), install_hint(package or module)


def tidy_check():
    try:
        import tidylib
        tidylib.Tidy()                     # loads the library, or raises
        found = 'libtidy'
    except (ImportError, OSError):
        found = None
    hint = 'brew install tidy-html5' if sys.platform == 'darwin' else 'sudo apt install libtidy-dev'
    return 'libtidy', found, hint


def chromium_check():
    """The Chromium of Playwright: launched and closed, the surest test."""
    hint = f'{sys.executable} -m playwright install --only-shell chromium'
    if importlib.util.find_spec('playwright') is None:
        return 'Chromium', None, hint
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            found = f'Chromium {browser.version} (Playwright)'
            browser.close()
    except Exception:          # not installed, or does not start: what to run is the same
        found = None
    return 'Chromium', found, hint


def playwright_checks(chromium):
    """playwright, pypdf (the extra lhtml-site[pdf]); `chromium`: chromium_check()."""
    extra = ('pipx inject lhtml-site playwright pypdf' if installation() == 'pipx'
             else f'{sys.executable} -m pip install "lhtml-site[pdf]"')
    playwright, pypdf = [(name, found, extra) for name, found, _ in (module_check('playwright'),
                                                                      module_check('pypdf'))]
    return playwright, pypdf, chromium


def features():
    """The optional features and their checks, in the order of the README."""
    playwright, pypdf, chromium = playwright_checks(chromium_check())
    return [
        ('PDF export (theme slides-pdf, export: pdf; lhtml-site[pdf])', [playwright, pypdf, chromium]),
        ('Layout report (--layout, --render; playwright of lhtml-site[pdf])', [playwright, chromium]),
        ('Videos in several codecs (cache_video_directory)',
         [system_check('ffmpeg'), ('ffpb', find_command('ffpb'), install_hint('ffpb', command=True))]),
        ('SASS (.sass files)', [module_check('sass', 'libsass')]),
        ('Figures in code (the libraries of their scripts, TikZ)',
         [module_check('matplotlib'), module_check('numpy'), system_check('latex'), system_check('dvisvgm')]),
        ('Code of other repositories (plugins/code_include.py)', [system_check('git')]),
        ('HTML cleaned by tidy (use_tidy: true)', [tidy_check()]),
    ]


def version(distribution):
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def report_lines(checked):
    lines = []
    for feature, checks in checked:
        missing = [name for name, found, _ in checks if not found]
        lines.append('')
        lines.append(f"{feature}: {'ready' if not missing else 'missing ' + ', '.join(missing)}")
        for name, found, hint in checks:
            lines.append(f'  ok       {name:10} {found}' if found else f'  missing  {name:10} -> {hint}')
    return lines


def main(arguments):
    parser = argparse.ArgumentParser(
        prog='lhtml-site doctor',
        description='Say what is present and what is missing for each optional feature of the generator '
                    '(PDF export, layout report, videos, ...), and how to install it. Changes nothing.')
    parser.parse_args(arguments)
    kind = installation()
    lhtml = version('lhtml-markup')
    print(f"lhtml-site {version('lhtml-site') or '(not installed)'}, "
          f"Python {sys.version.split()[0]} ({sys.executable})")
    where = {'checkout': f'a checkout ({PACKAGE.parents[1]})', 'pipx': f'pipx ({sys.prefix})',
             'pip': f'pip ({sys.prefix})'}[kind]
    print(f'Generator: {PACKAGE}, from {where}')
    if kind == 'pipx':
        print('Python packages go into its environment: pipx inject lhtml-site <package> '
              '(pip install reaches another Python)')
    too_old = lhtml is None or int(lhtml.split('.')[0]) < 3
    print('')
    print(f"HTML pages and slides (themes webpage-frame, slides): "
          f"{'ready' if not too_old else 'lhtml-markup 3.0 or later is needed: ' + install_hint('-U lhtml-markup')}"
          f" (lhtml-markup {lhtml or 'not found'})")
    for line in report_lines(features()):
        print(line)
    return 0
