# lhtml-site: development

The layout of the repository and the tests. The use of the generator is in the
[README](../../../README.md) and the [reference](reference.md).

## Project Structure

```
lhtml-site/
  generate.py              # Runs the generator of the checkout (python generate.py = lhtml-site)
  pyproject.toml           # The package lhtml-site and its command
  requirements.txt         # Python dependencies (requirements-lock.txt: versions, requirements-dev.txt: tests)
  tests/                   # pytest suite
  src/lhtml_site/          # The package: its code, and the files it reads next to it
    generate.py            # The pipeline, and the command (main)
    configure_example.yaml # Commented example configuration (lhtml-site init)
    doctor.py              # lhtml-site doctor: the tools of the optional features, found or not
    build_output.py        # Build in a staging directory, published only on success
    configuration.py       # Validated Config and BuildContext plugin adapter
    development.py         # --serve / --watch, server of the comments
    feedback.py, feedback.js  # Comments on the render (--serve)
    source_scan.py         # Reading of the sources as LHTML reads them (code, comments, Jinja, URLs)
    source_map.py          # data-lhtml-src="file:line" on the blocks (builds for development)
    tracking.py            # Templates and includes read by each page
    dependencies.py        # Files each page depends on: --only, validity of the reports
    pages.py               # Pages: sources, templates, occurrences, placement in the site
    pdf_export.py          # The PDF of a target whose theme declares export: pdf
    browser.py             # The headless Chromium (Playwright): PDF export, layout report, --render
    project.py             # A project: its decks, each built to its targets
    video_convert/         # Video conversion utilities (ffmpeg)
    deck.py                # Deck: order of the slides (deck.yaml)
    design.py              # Design tokens, macros and layouts (design.yaml -> design.css)
    theme.py               # What a theme declares about the build (theme.yaml)
    menu.py                # The table of contents written into the theme's menu
    headings.py            # Heading ids (from the text, or once Jinja rendered it)
    wrap.py                # The page placed in the template of its theme
    index_page.py          # The index of a site that has none
    video_cache.py         # Transcoded variants of the videos (cache_video_directory:)
    lint.py                # Design lint: values written by hand in the pages
    design_checks.py       # Checks of the layout report by role (title, body, caption, figure)
    report_lock.py         # One build at a time writes the layout report
    credits.py             # Credits, origin of the slides, planned figures (.structure/credits.md, todo.md)
    figures.py             # Figures made from code (*.svg.py, *.svg.tex)
    filesystem.py          # File/directory utilities
    generator_tool.py      # Metadata extraction, sitemap generation
    logger.py              # Console output (rich)
    layout_options.py      # Options of the layout report, checked by --check-config
    layout/
      analysis.py          # What a measured page shows: collisions, overflows, density, deviations
      findings.py          # The checks: their code, their severity, their sentence
      report.py            # layout.md, summary.md, changes.md and the contact sheets
      measure.py           # Measurement in headless Chromium (Playwright), images of the report, --render
      page.js              # What runs inside the page: the blocks, the overlays, the media frozen
      build.py             # The analysis of a build (--layout): which pages, what to keep, where
    structure.py           # Pages of the site for plugins (structure, built_pages),
                           #   what may be published, and .structure/ of a project
    plugins/
      pre_include.py       # Pre-include content into templates
      code_include.py      # Include code from external repos
    themes/                # each with theme.yaml (contract with the build)
      webpage-frame/       #   and, for the slides, design.yaml (tokens, macros)
      slides/              # Presentation slides theme
      slides-pdf/          # PDF export slides theme
    docs/                  # reference.md, development.md, and agents.md: procedure for AI agents
                           #   writing slides (copied into .structure/)
    starters/              # The pages lhtml-site init copies into src/: slides/, site/
    example/               # Complete demo (a course, with videos): in the checkout, not in the
                           #   package (pyproject.toml)
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q -n auto
```

Most tests run a build in a subprocess, so they are slow one after the other and almost free in parallel: `-n auto` (pytest-xdist) takes the suite from about 85 s to 15 s, and about 110 s to 30 s with the browser tests. Drop `-n auto` to read the output of a single test.

Development dependencies are listed separately in `requirements-dev.txt` and share the version lock. When Node.js is on the PATH, the tests also run the generated menu JavaScript and the heading reader in it (skipped otherwise); the generator itself does not use Node. The suite covers configuration precedence, validation, path protection, read-only diagnostics, plugin context isolation, generation regressions, and simulated PDF tool failures.

The GitHub Actions workflow runs on pushes and pull requests, on Python 3.11 and 3.14. It installs the Chromium of Playwright (`python -m playwright install --with-deps --only-shell chromium`), runs the suite and real Chromium/HTTP smoke tests: the layout report and the PDF export of the slides starter included. Its job `package` follows the publishing path: it builds the wheel and the sdist, runs `twine check --strict`, checks that the wheel holds no build output nor the demo and stays under 15 MB, installs it in a clean environment and runs `lhtml-site init` and a build outside the repository, then the wheel with the extra `pdf`, a PDF export and a layout report by Playwright (`tests/test_packaging.py` checks the content of the wheel locally). `.github/workflows/publish.yml` publishes to PyPI with Trusted Publishing; it is prepared, not enabled: it runs only by hand, and its header says how to enable it. Run these locally after `python -m playwright install --only-shell chromium`:

```bash
LHTML_BROWSER_TEST=1 LHTML_PREVIEW_TEST=1 python -m pytest tests/test_layout_integration.py tests/test_development.py tests/test_pdf_export.py -q
```

Checking a change against a real deck: a full `--layout` measures every page, which is the slow way. `--only` rebuilds and re-measures the pages named and keeps the reports of the others, so the summary still counts the whole deck:

```bash
lhtml-site -i <deck>/configure.yaml --layout --only <page> --only <other page>
```

On a deck of 78 slides, four pages measured this way take 11 s against 45 s, and report the same totals. Measuring a *subset deck* instead would not: the table of contents and the deck norms are computed over the slides present, so a shorter deck has a different navigation, and findings that involve it disappear.

The browser and HTTP tests are opt-in locally because they launch Chrome and bind a localhost port. When updating dependencies, update `requirements-lock.txt`, install into a fresh environment, and run both the unit suite and smoke tests before committing. Optional PDF/SASS system tools are not part of the Python lock.

**Windows.** `tests/windows.sh <ssh host> [<lhtml checkout>]` copies this checkout and an LHTML checkout (default `../../lhtml/lhtml`, from the root of this one) to a Windows machine over SSH, installs LHTML from that checkout and runs both suites there (Windows 11, Python 3.14: they pass, and the example site built there is identical to the one built on macOS). On Windows, `py -3` is the reliable launcher: another program may put its own `python` first in the `PATH`.
