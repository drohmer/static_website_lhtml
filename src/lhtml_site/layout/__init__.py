"""The layout analysis: measure a page, judge what it shows, write the report.

    analysis.py   the checks on the measured blocks (pure functions)
    report.py     the markdown and the contact sheets written from them
    measure.py    headless Chromium, through Playwright (page.js: what runs in the page)
    build.py      the analysis of a build (--layout): which pages to measure,
                  what to keep of a previous build, where to write

The first three know nothing of a build: a layout.json is enough to run
them, which is what makes them testable one by one. Everything that depends
on a build is in build.py, and nothing else of the generator depends on it.
"""
