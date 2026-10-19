"""lhtml-site doctor: what is present and what is missing, feature by feature.

A site of HTML pages or slides needs nothing more than the package. Each
optional feature needs its own programs (Playwright, or Node and puppeteer,
for the PDF export, Node for the layout report, ffmpeg for the videos, ...): this command says,
for each, what it found and how to install what it did not, for the way the
generator is installed (a checkout, pipx, a virtual environment). It changes
nothing.

The helpers of this module are also those of the build, so that the build
and the diagnosis look for the same things in the same places:
`find_command`, `install_hint`, `node_environment`.
"""
import argparse
import importlib.metadata
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
SCRIPTS = PACKAGE / 'plugins' / 'assets'
# Where the Node modules of an installed generator go (README, "PDF export
# with pipx"): the Node scripts find them there without NODE_PATH.
NODE_HOME = Path.home() / '.lhtml-site'
NODE_MODULES = NODE_HOME / 'node_modules'


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


def playwright_install_command():
    """The command that installs playwright and pypdf (the extra
    lhtml-site[pdf]). After pipx, two injections: pypdf has no command, and
    `--include-apps` fails on a package without one."""
    if installation() == 'pipx':
        return 'pipx inject lhtml-site pypdf, then pipx inject --include-apps lhtml-site playwright'
    return f'{shlex.quote(sys.executable)} -m pip install "lhtml-site[pdf]"'


def playwright_browser_command():
    """The command that downloads the Chromium of the Playwright of the
    generator: after pipx, the command `playwright` that `pipx inject
    --include-apps` put on the PATH (no path of pipx to type); otherwise the
    Python of the generator."""
    if installation() == 'pipx':
        return 'playwright install --only-shell chromium'
    return f'{shlex.quote(sys.executable)} -m playwright install --only-shell chromium'


def find_command(name):
    """A program on the PATH, or next to the Python that runs the generator
    (a command installed with it, by pip or `pipx inject`); None if neither."""
    return shutil.which(name) or shutil.which(name, path=os.path.dirname(sys.executable))


def node_environment():
    """The environment of the Node scripts: NODE_PATH ends with NODE_MODULES
    when it exists, so that an installed generator finds puppeteer there."""
    env = dict(os.environ)
    if NODE_MODULES.is_dir():
        env['NODE_PATH'] = os.pathsep.join(p for p in (env.get('NODE_PATH'), str(NODE_MODULES)) if p)
    return env


# ---------------------------------------------------------------------------
# The checks: (name, what was found or None, how to install it)
# ---------------------------------------------------------------------------

SYSTEM = {   # program: (what provides it, macOS, Debian/Ubuntu)
    'node': ('Node.js', 'brew install node', 'https://nodejs.org (or apt install nodejs npm)'),
    'pdfunite': ('poppler', 'brew install poppler', 'sudo apt install poppler-utils'),
    'pdftoppm': ('poppler', 'brew install poppler', 'sudo apt install poppler-utils'),
    'magick': ('ImageMagick 7', 'brew install imagemagick', 'https://imagemagick.org (magick)'),
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


def node_report():
    """What plugins/assets/doctor.js says (node, puppeteer, Chrome); {} without node."""
    node = shutil.which('node')
    if node is None:
        return {}
    try:
        result = subprocess.run([node, str(SCRIPTS / 'doctor.js')], capture_output=True, text=True,
                                timeout=60, env=node_environment(), cwd=SCRIPTS)
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (subprocess.SubprocessError, json.JSONDecodeError, IndexError, OSError):
        return {'node': node}            # a node that does not run the script: the rest is missing


def node_checks(report, pdf=False):
    """node, puppeteer, minimist, Chrome: those of the Node scripts (report: node_report()).
    The Chrome installed on the machine is a last resort of the layout report;
    the PDF export does not launch it (macOS: it fails to start with the
    options of the export), it needs the Chrome of puppeteer."""
    checkout = installation() == 'checkout'
    npm = (f'npm ci (in {PACKAGE.parents[1]})' if checkout
           else f'npm install --prefix {NODE_HOME} puppeteer minimist')
    browsers = ('npx puppeteer browsers install chrome' if checkout
                else f'{NODE_MODULES}/.bin/puppeteer browsers install chrome')
    if report.get('asked'):
        chrome = report['asked'] + ' (PUPPETEER_EXECUTABLE_PATH)'
    elif report.get('downloaded'):
        chrome = report['downloaded']
    elif report.get('installed') and not pdf:
        chrome = report['installed'] + ' (installed on the machine, used as a last resort)'
    else:
        chrome = None
    browser_hint = (f'{browsers} (the Chrome of puppeteer: not the one installed on the machine)' if pdf
                    else f"{browsers}, or the configuration key 'chrome'")
    node_hint = system_check('node')[2]
    return [('node', report.get('node') or None, node_hint),
            ('puppeteer', report.get('puppeteer') or None, npm),
            ('minimist', report.get('minimist') or None, npm),
            ('Chrome', chrome, browser_hint)]


def chromium_check():
    """The Chromium of Playwright: launched and closed, the surest test."""
    hint = playwright_browser_command()
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


def playwright_checks():
    """playwright, pypdf (the extra lhtml-site[pdf]) and its Chromium."""
    pipx = installation() == 'pipx'
    extra = f'{sys.executable} -m pip install "lhtml-site[pdf]"'
    hints = {'playwright': install_hint('playwright', command=True) if pipx else extra,
             'pypdf': install_hint('pypdf') if pipx else extra}
    return [(name, found, hints[name]) for name, found, _ in (module_check('playwright'), module_check('pypdf'))] \
        + [chromium_check()]


def features():
    """The optional features and their checks, in the order of the README."""
    report = node_report()
    pdf_tools = [system_check('pdfunite'), system_check('pdftoppm'), system_check('magick')]
    return [
        ('PDF export with Playwright (theme slides-pdf, export: pdf; lhtml-site[pdf])', playwright_checks()),
        ('PDF export with Node (the fallback: LHTML_PDF_ENGINE=node)', node_checks(report, pdf=True) + pdf_tools),
        ('Layout report (--layout, --render)', node_checks(report)),
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
    from lhtml_site import pdf_export
    try:
        print(f'\nThe PDF export uses: {pdf_export.engine()} '
              '(playwright when playwright and pypdf are installed; LHTML_PDF_ENGINE=node or playwright chooses)')
    except ValueError as error:
        print(f'\n{error}')
    if NODE_MODULES.is_dir():
        print(f'\nNode modules of {NODE_MODULES} are found by the generator (no NODE_PATH needed).')
    return 0
