# Changelog

All notable changes to lhtml-site (`lhtml-site` on PyPI) are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [3.0.0] - unreleased

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

### Changed
- Requires LHTML 3 (`lhtml-markup>=3.0`), which reads no file: the
  generator reads the sources, and `include::` is written with Jinja
  (`{% include %}`). Coming from LHTML 2: the
  [migration of LHTML](https://github.com/drohmer/lhtml/blob/main/docs/migration.md).
- The README leads to a first talk in a few commands; the reference moves
  to [docs/reference.md](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md).
- The themes `slides` and `slides-pdf` show a bullet before the items of a
  list (a circle for a sub-point); they showed none. A slide that wrote its
  own marker (`* - point`) can drop it.
- The package holds the themes, plugins and starters but not the demo
  course, and the themes ship their fonts as WOFF2 only: the wheel is about
  8 MB.

[3.0.0]: https://github.com/drohmer/lhtml-site/releases/tag/v3.0.0
