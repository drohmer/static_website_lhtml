# Changelog

All notable changes to lhtml-site (`lhtml-site` on PyPI) are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- The "Page content" column of the theme webpage-frame is read in the page
  (its level-2 headings with an id), not fetched from a JSON file: it is
  shown when the site is opened from disk (`file://`), where it was empty,
  and lists the headings as the page shows them (`== One **bold**` is
  "One bold", it was "One \*\*bold\*\*").
- A heading whose text comes from Jinja gets its id from its text as
  rendered, unique in its page: each occurrence of a page reused with
  `params` has the id of its own title (`interpolation_de_key_l1`; it was
  `_parties[current__1]_id2_l1`, the same source for all of them), and
  each heading of a `{% for %}` loop has its own. The ids of the headings
  written as text do not change: links into published sites keep working.

### Removed
- The site no longer holds `<page>.title_id.json`, `title_id.json` nor
  `structure/title_id.json` (144 files, 592 KB on a deck of 78 slides).
  The record of the headings that `--only` needs is build state, in
  `.verification/headings.json`; the `structure/title_id.json` of a site
  built by 3.0 is read once in its place.

## [3.0.0] - 2026-10-19

The first release on PyPI. The generator was named `static_website_lhtml`,
and projects used it as a copy or a submodule; it is now a package with a
command, `lhtml-site`, and its version follows the major version of LHTML
it is built on.

### Added
- `pipx install lhtml-site` (or `pip install lhtml-site` in a virtual
  environment) installs the command `lhtml-site`; `lhtml-site --version`
  says its version and the LHTML it runs.
- `lhtml-site init [DIR] [--theme slides|slides-pdf|webpage-frame]` creates
  a project: a `configure.yaml` and pages to start from in `src/` (four
  slides, or two web pages). Over a directory that already has its pages in
  `src/`, it writes only `configure.yaml`.
- `lhtml-site doctor` says, for each optional feature (PDF export, layout
  report, videos, SASS, figures, code snippets, tidy), what it finds and the
  command that installs what is missing for the way lhtml-site is
  installed (`pipx inject` after pipx).
- `lhtml-site --serve --watch` builds, serves the site on localhost and
  rebuilds it on save.
- A page says what it is in its front matter (the YAML at its top), and may
  be written in Markdown (`index.md.j2`) as well as in LHTML
  (`index.html.j2`).
- Projects of several decks, each built to several targets (the slides in
  the browser, a PDF), the layout report (`--layout`), the lint of the
  values written by hand (`--lint`).
- The PDF export runs Chromium through Playwright for Python, with the extra
  `lhtml-site[pdf]` (playwright, pypdf) and
  `python -m playwright install --only-shell chromium`: no Node.js, poppler
  nor ImageMagick. One browser for the deck, a few slides at a time, each
  printed once ready (fonts, math, images, a frame of each video) instead of
  after a fixed 4 s; the images are screenshots at 3840 px, the merge is
  pypdf. The outputs keep their names and layout. `lhtml-site doctor`
  reports it.
- A progress bar while the PDF is made, on a terminal only (a log gets
  nothing). Without Playwright nor the Node export, the build says to
  install Playwright, the command for the way lhtml-site is installed.

### Changed
- Requires LHTML 3 (`lhtml-markup>=3.0`), which reads no file: the
  generator reads the sources, and `include::` is written with Jinja
  (`{% include %}`). Coming from LHTML 2: the
  [migration of LHTML](https://github.com/drohmer/lhtml/blob/main/docs/migration.md).
- The README leads to a first talk in a few commands; the reference moves
  to [docs/reference.md](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md).
- The package holds the themes, plugins and starters but not the demo
  course, and the themes ship their fonts as WOFF2 only: the wheel is about
  8 MB.
- The id of a heading is the one of the generator copied into projects
  since April 2026 (` -,.:()` become `_`, then `__` becomes `_`), so links
  into the sites it built keep working; a site built by an older copy
  changes the id of its headings with these characters (`Part - One`:
  `part___one` before, `part__one` now). A repeated heading gets distinct
  ids (`_id2`, `_id3`...) and characters unsafe in a URL are removed.
- The Node export (puppeteer, poppler, ImageMagick) is the fallback: used
  when Playwright is not installed, or with `LHTML_PDF_ENGINE=node`.

[3.0.0]: https://github.com/drohmer/lhtml-site/releases/tag/v3.0.0
