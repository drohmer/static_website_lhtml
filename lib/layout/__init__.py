"""The layout analysis: measure a page, judge what it shows, write the report.

It depends on the measurement and on nothing else of the build, so that it
can be read, tested and run outside a build:

    analysis.py   the checks on the measured blocks (pure functions)
    report.py     the markdown and the contact sheets written from them
    measure.py    headless Chrome, through the Node scripts of plugins/assets/

plugins/layout_report.py is the hook that calls them during a build.
"""
