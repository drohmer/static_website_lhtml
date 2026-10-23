# Changelog

All notable changes to lhtml-site (`lhtml-site` on PyPI) are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- The `slides` theme: a horizontal swipe goes to the next slide (to the
  left) or the previous one (to the right), on a phone, a tablet or a touch
  screen. A pinch, a vertical scroll, a page zoomed in, and a swipe on a
  video, a form, the menu or a block that scrolls sideways (code) are left
  to the browser.

### Fixed
- The transcoded videos: only the variants of the videos of the pages built
  are copied into the site, not the whole `cache_video_directory`. The cache
  of a page removed was published with the site. A full build now names the
  directories of the cache that belong to no video of the site, and removes
  nothing (`--only` builds some pages, and says nothing of the others).

## [1.0.0] - 2026-10-19

The first release on PyPI. The generator was named `static_website_lhtml`,
and projects used it as a copy or a submodule; it is now a package with a
command, `lhtml-site`, built on LHTML 3 (`lhtml-markup` on PyPI).

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
  nothing). Without Playwright, the build says what to install, the command
  for the way lhtml-site is installed.
- The layout report (`--layout`, `--render`) runs in the same Chromium,
  through Playwright for Python (`lhtml_site/layout/measure.py`; what runs
  inside the page is `lhtml_site/layout/page.js`). Its reports are those of
  the Node version: same blocks, problems and usual values of the deck
  measured in the same browser. The pages of an existing report are measured
  again once (the measuring code changed). On a deck of 35 slides, the
  report takes 7.9 s instead of 9.5 s.
- A slide is printed once the promises a page or a demo (in an iframe too)
  registered with `window.__lhtmlReady` are settled, as the layout report
  already waited for them; the whole preparation of a slide is bounded (60
  s), so a promise that never settles fails the slide instead of blocking
  the export. After pipx, the commands to install are the same in the
  README, in `lhtml-site doctor` and in the errors:
  `pipx inject lhtml-site pypdf`, `pipx inject --include-apps lhtml-site
  playwright`, then `playwright install --only-shell chromium`.

### Changed
- Requires LHTML 3 (`lhtml-markup>=3.0`), which reads no file: the
  generator reads the sources, and `include::` is written with Jinja
  (`{% include %}`). Coming from LHTML 2: the
  [migration of LHTML](https://github.com/drohmer/lhtml/blob/main/docs/migration.md).
- The README leads to a first talk in a few commands, opened from the disk
  (`lhtml-site`, then `.site/index.html`; `--watch` to rebuild on save, and
  `init` says the same); the reference moves to
  [docs/reference.md](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md),
  with the details of the PDF export.
- The package holds the themes, plugins and starters but not the demo
  course, and the themes ship their fonts as WOFF2 only: the wheel is about
  8 MB.
- The id of a heading is the one of the generator copied into projects
  since April 2026 (` -,.:()` become `_`, then `__` becomes `_`), so links
  into the sites it built keep working; a site built by an older copy
  changes the id of its headings with these characters (`Part - One`:
  `part___one` before, `part__one` now). A repeated heading gets distinct
  ids (`_id2`, `_id3`...) and characters unsafe in a URL are removed.
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
- Node.js is no longer used: the Node PDF export of `static_website_lhtml`
  (puppeteer, poppler, ImageMagick, `LHTML_PDF_ENGINE`), the Node scripts of
  the layout report, `package.json`. `lhtml-site doctor` no longer looks for
  Node, puppeteer or a Chrome of its own.
- The site no longer holds `<page>.title_id.json`, `title_id.json` nor
  `structure/title_id.json` (144 files, 592 KB on a deck of 78 slides).
  The record of the headings that `--only` needs is build state, in
  `.verification/headings.json`; the `structure/title_id.json` of a site
  built by an older copy is read once in its place.

### Fixed
- The slides no longer write their menu in the console of the browser.

[1.0.0]: https://github.com/drohmer/lhtml-site/releases/tag/v1.0.0
