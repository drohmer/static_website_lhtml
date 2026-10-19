"""The headless browser of the generator: the Chromium of Playwright for
Python, run by the PDF export (lhtml_site/pdf_export.py), the layout report
and --render (lhtml_site/layout/measure.py).

Playwright comes with the extra `lhtml-site[pdf]`, its browser from
`python -m playwright install --only-shell chromium`; the configuration key
'chrome' runs another Chrome instead.
"""
import importlib.util
import re
import sys
from contextlib import asynccontextmanager

PLAYWRIGHT_MISSING = ('{feature} needs {modules}: {install}, '
                      'then {python} -m playwright install --only-shell chromium')
CHROMIUM_MISSING = ('The Chromium of Playwright is not installed: {python} -m playwright install --only-shell chromium '
                    '(or the configuration key chrome)')


def installed(modules=('playwright',)):
    return all(importlib.util.find_spec(module) for module in modules)


def require(feature, modules=('playwright',)):
    """Raise a RuntimeError saying how to install `modules` when one of them
    is missing (`feature`: 'The layout report', ...)."""
    if installed(modules):
        return
    names = ' '.join(modules)
    install = (f'pipx inject lhtml-site {names}' if re.search(r'pipx[/\\]venvs', sys.prefix)
               else f'{sys.executable} -m pip install "lhtml-site[pdf]"')
    raise RuntimeError(PLAYWRIGHT_MISSING.format(feature=feature, modules=' and '.join(modules),
                                                 install=install, python=sys.executable))


@asynccontextmanager
async def chromium(chrome_path=None, args=()):
    """A headless Chromium: the one of Playwright, or the executable
    `chrome_path` (the configuration key 'chrome')."""
    from playwright.async_api import Error, async_playwright

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(executable_path=chrome_path or None, args=list(args))
        except Error as error:
            if "Executable doesn't exist" in str(error):
                raise RuntimeError(CHROMIUM_MISSING.format(python=sys.executable)) from None
            raise
        try:
            yield browser
        finally:
            await browser.close()


def first_line(error):
    """The first line of what a Playwright error says (the rest is its call log)."""
    return (str(error).strip().splitlines() or [type(error).__name__])[0]
