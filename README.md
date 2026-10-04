# Static Website LHTML

A static site generator built on [LHTML](https://github.com/drohmer/lhtml) and Jinja2. Transforms template sources (`.html.j2` with LHTML markup) into a complete static website.

## Installation

```bash
git clone https://github.com/drohmer/static_website_lhtml.git
cd static_website_lhtml
pip install -r requirements.txt
```

**Python**: 3.11 or newer. Runtime and transitive dependencies are pinned in `requirements-lock.txt`; `requirements.txt` applies these constraints. Use `npm ci` to install the locked Node dependencies.

**Dependencies**: `lhtml-markup` (2.5 or later), `Jinja2`, `jinja-markdown`, `pytidylib`, `pyyaml`, `rich`

Optional:
- **PDF export** (`generate_pdf.py`): Node.js, then `npm install` in this directory (installs `puppeteer`, which downloads a headless Chrome, and `minimist`, see `package.json`), plus `pdfunite`/`pdftoppm` (poppler) and ImageMagick (`magick`) for the slide images. Put `generate_pdf.py` last in the plugin list: after the export, it removes the site directory (kept with `-d`).
- **SASS**: `pip install libsass` to compile `.sass` files (a warning is shown if they are left uncompiled).

## Quick Start

```bash
python generate.py -i configure_example.yaml
```

This generates a site from `example/` into `.site/` using the default theme.

For your own project, copy and edit the config:

```bash
cp configure_example.yaml configure.yaml
# Edit configure.yaml with your source/theme paths
python generate.py
```

## CLI Options

```
python generate.py [-i config.yaml] [-d | --no-debug] [-c] [--only POINTER] [--lint] [--check-config] [--layout] [--deck FILE] [--scaffold] [--serve] [--watch] [--port PORT]

  -i, --input_config   YAML configuration file (default: configure.yaml)
  -d, --debug          Display debug info and keep temporary files
      --no-debug       Override debug: true from YAML
      --check-config   Validate paths and plugin files; display resolved settings
  -c, --clean          Remove only the configured output directory and exit
  --only POINTER       Generate only these pages in the existing site (see below; repeatable)
  --lint               List the values written by hand in the pages, with the layout or macro
                       replacing them (see Design); no generation (with --only: some pages)
  --serve              Serve the generated site on http://127.0.0.1:8000/
  --watch              Rebuild after source, theme, plugin or configuration edits
  --port PORT          HTTP port (default: 8000; 0 selects an available port)
  --layout             Write a layout report of each page in .layout/ (see below)
  --deck FILE          Order of the slides: deck file replacing the 'deck' of the configuration
                       (relative to the current directory, else to the configuration file)
  --scaffold           Create the source of the deck slides that do not exist yet
```

## Local preview

```bash
python generate.py --serve --watch
```

The server binds only to localhost. Open the printed URL, and refresh the browser after a rebuild. `--serve` can be used alone; `--watch` can rebuild without an HTTP server. Stop with Ctrl+C. The watcher polls inputs and waits for saves to settle. It watches the source, theme, YAML configuration, deck and design files (with the files they `extends`), configured plugin files and `pre_include` files. It does not follow directory symlinks or watch remote repositories. With `--only`, each edit regenerates only those pages. Changes to assets and configuration are included. Invalid edits leave the previous site available, and a later edit retries the build.

**Comments on the render.** With `--serve`, the pages have a button 💬 (or
the key `c`): click a block, write a comment, save. The comments are kept next
to the configuration in `.feedback/comments.md` (and `comments.jsonl`), with
the page and the file and line of the block (source map), for an agent or the
author to treat; open comments are shown on the pages as numbered pins (click:
read, "Done"). Only the script of the served pages can write them (custom
header and JSON, refused to other sites).

Builds run in a hidden temporary sibling directory. Only a successful build replaces the output; failures preserve the previous site. With `--debug`, failed staging directories are kept and their location is reported. Publication uses a backup/rename with rollback on failure; there is a brief directory swap, not an atomic filesystem exchange. Plugin side effects outside the site directory (reports, PDF, caches or custom actions) are not covered by the site transaction. PDF-only exports can remove their staged HTML on success; an existing published site is retained.

### Generating some pages (`--only`)

```bash
python generate.py --only 03_squelette/04_ik --layout   # one slide, and its layout report
python generate.py --only 02_rotations --only inf585:04_interpolation_position/content/07_hermite
```

`--only` takes pointers written as in a deck (directory, file, glob,
`name:path`; all the occurrences of a repeated slide) and generates only
these pages, in the site itself: their template, the files of their
directory (assets), the menu, the sitemap and the structure of the site; the
other pages are those of the previous build. Their numbering, their links
(`pathTo_*`) and the ids of the titles are those of a full build. A page that
fails keeps its previous version. When there is no previous build, or when
the pages of the site changed (deck, new, renamed or removed page), a full
build is done instead. Edits of the theme or of files outside the page
directories (shared images, sources included from elsewhere are read from the
sources) need a full build.

## Configuration

```yaml
source_directory: 'example/'           # Source content directory
site_directory: '.site/'               # Output directory
theme: 'themes/webpage-frame/'         # Theme directory
plugin:                                # Plugin list (executed in order)
  - 'plugins/menu.py'
  - 'plugins/redirection_first_page.py'
```

Configuration precedence is **built-in defaults → the selected YAML file → explicit CLI options**. Only one YAML file is loaded: `configure_example.yaml` is a commented example, not a second layer of defaults. The authoritative defaults are in `Config` in `lib/configuration.py`.

Relative paths are resolved from the YAML file's directory, independent of the shell's working directory. Absolute paths and `~` are supported. If omitted, `site_directory` defaults to `.site/`, `source_directory` to `src_site/`, and `theme` to the generator's bundled `webpage-frame` theme. An explicitly configured relative theme path is relative to the YAML file.

Configuration values are type-checked before generating or cleaning. Unknown keys produce warnings (with spelling suggestions) but remain available to custom plugins. Runtime fields such as `log`, `args`, and `plugin_paths` cannot be supplied in YAML. Prefer `plugin_arg` for custom plugin options.

The output directory must not overlap the source or theme directory, even via symbolic links. It must not contain the configuration file, generator installation, or configured video cache. These checks apply to both generation and `--clean`. Cleaning does not require the source/theme to still exist and does not remove Python caches from the working directory.

Check a project without running plugins, generating the site, or deleting outputs:

```bash
python generate.py -i configure.yaml --check-config
```

This reports the resolved paths, selected plugin files and logging settings. Missing plugins fail validation before the previous site is touched. The check validates plugin file presence, not plugin execution or optional external dependencies. `--check-config` takes precedence if combined with `--clean`.

Optional keys:

| Key | Description |
|-----|-------------|
| `debug` | Verbose logging and retained intermediate files; overridden by `--debug` / `--no-debug` |
| `level_print` | Non-negative log indentation level (default: 0) |
| `include_head` | List of extra head fragments passed to LHTML |
| `cache_video_directory` | Directory for cached video codec conversions |
| `use_tidy` | Enable HTML tidy post-processing (default: false) |
| `keywords` | Extra Jinja2 template variables |
| `plugin_arg` | Arguments passed to specific plugins |
| `title_id` | Generate heading IDs (default: true) |
| `deck` | Order of the pages: path of a deck file, or mapping/list of slides (see [Deck](#deck-order-of-the-slides)); without deck, the order of the files |
| `design` | Tokens, macros and layouts overriding the theme's `design.yaml` (mapping, or path of a YAML file; see [Design](#design-tokens-macros-and-layouts)) |

## Pipeline

The generator runs the following stages:

1. **Data preparation** — Find the `.html.j2` templates, select and order them (deck), copy the sources and theme to the site (or, with `--only`, the templates and assets of its pages), extract titles and sitemap, export `structure/`, write the design (`design.css`, `design.md`)
2. **Pre-process plugins** — Plugin hooks before Jinja2 rendering
3. **Jinja2 rendering** — Render the templates with their variables (see [Template variables](#template-variables))
4. **Mid-process plugins** — Plugin hooks between Jinja2 and LHTML
5. **LHTML conversion** — Convert LHTML markup to HTML, with optional tidy
6. **SASS compilation** — Compile `.sass` files to `.css` (if libsass installed)
7. **Post-process plugins** — Plugin hooks after all conversions

## Template variables

Each page is rendered by Jinja2 with:

| Variable | Value |
|----------|-------|
| `pathToRoot` | Relative path to the root of the site (`../../`) |
| `pageID` | Number of the page in the site (order of the files or of the deck), from 0 |
| `pathTo_<id>` | Relative link to the page `<id>` of the sitemap (`<id>`: its title in lower case with `_` for spaces, or the value of `{% set title_id = '...' %}`; `_1`, `_2`... for repeated titles) |
| `linkTo_<id>` | `<a href="...">` to that page |
| `params` | Parameters of the occurrence given by the deck (`params.current`), empty otherwise |
| `page` | Metadata of the page: its `config.yaml` and deck entry (`page.notes`, `page.layout`), title, place in the site |
| `layout` | Layout of the page, when the page sets it (`{% set layout = 'side' %}`, see [Design](#design-tokens-macros-and-layouts)) |
| `credit(file)`, `credits` | Credit of a file of the page, credits of all the pages (see [Credits](#credits-origin-of-the-slides-figures-in-code)) |
| keys of `keywords` | Values of the configuration (`params`, `page`, `credit`, `credits` are reserved) |

`{% extends %}`, `{% include %}` and `{% import %}` read the templates of the
project (relative to its source directory), then of the other projects of the
deck, then of the site (`theme/template/base.html`).

## Project Structure

```
static_website_lhtml/
  generate.py              # Main generator
  configure_example.yaml   # Commented example configuration
  requirements.txt         # Python dependencies (requirements-lock.txt: versions, requirements-dev.txt: tests)
  package.json             # Node dependencies (puppeteer: PDF export, layout report)
  lib/
    build_output.py        # Build in a staging directory, published only on success
    configuration.py       # Validated Config and BuildContext plugin adapter
    development.py         # --serve / --watch, server of the comments
    feedback.py, feedback.js  # Comments on the render (--serve)
    source_map.py          # data-src="file:line" on the blocks (builds for development)
    pages.py               # Pages: sources, templates, occurrences, placement in the site
    deck.py                # Deck: order of the slides (deck.yaml)
    design.py              # Design tokens, macros and layouts (design.yaml -> design.css)
    lint.py                # Design lint: values written by hand in the pages
    credits.py             # Credits, origin of the slides, planned figures (structure/credits.md, todo.md)
    figures.py             # Figures made from code (*.svg.py, *.svg.tex)
    filesystem.py          # File/directory utilities
    generator_tool.py      # Metadata extraction, sitemap generation
    logger.py              # Console output (rich)
    structure.py           # Pages of the site for plugins (structure, built_pages)
  plugins/
    auto_wrap.py           # Auto-wrap plain HTML in Jinja2 template
    menu.py                # Generate JS menu from sitemap
    redirection_first_page.py  # Create index.html redirect
    title_submenu.py       # Extract heading IDs for navigation
    pre_include.py         # Pre-include content into templates
    code_include.py        # Include code from external repos
    cache_video.py         # Video codec conversion and caching
    generate_pdf.py        # PDF/image generation (requires puppeteer)
    layout_report.py       # Layout report (--layout, requires puppeteer)
    assets/                # Node scripts of the PDF export and of the layout report
    video_convert/         # Video conversion utilities (ffmpeg)
  tools/
    style_profile.py       # Style profile of a corpus of slide decks
  tests/                   # pytest suite
  themes/
    webpage-frame/         # Default web page theme
    slides/                # Presentation slides theme
    slides-pdf/            # PDF export slides theme
  docs/agents.md           # Procedure for AI agents writing slides (copied into structure/)
  example/                 # Example source content
```

## Themes

Three built-in themes are available:

- **`webpage-frame/`** — Standard website with navigation menu, suitable for documentation and course pages
- **`slides/`** — Presentation slides for browser display
- **`slides-pdf/`** — Presentation slides optimized for PDF export

Themes use Jinja2 template inheritance. The base template (`template/base.html`) provides blocks that content pages can override.

## Writing slides with an AI agent

[`docs/agents.md`](docs/agents.md) is the procedure for an agent (LLM) that
writes or edits slides: plan in the deck, layouts and macros, `--only
--layout`, `--lint`, how to read the report and when to stop. It does not
depend on the agent used. Each build copies it into `structure/agents.md` of
the site, and the layout report links to it. In a slide project, one line in
the file that your agent reads (`AGENTS.md`, `CLAUDE.md`, ...) is enough:

```
To write or edit the slides, follow <site>/structure/agents.md (e.g. _site/structure/agents.md).
```

## Deck: order of the slides

Without a deck, the pages are generated in the order of the files (sorted
paths, hence numbered directories such as `02_rotations/04_representations`).
A deck lists the slides with pointers to their sources, so that the order
does not depend on the names of the directories, slides can come from other
projects, and a slide can appear several times:

```yaml
# deck.yaml (configure.yaml: deck: 'deck.yaml')
title: Talk, short version
sources:                              # other projects (relative to the deck file)
  inf585: ~/teaching/inf585/lecture/inf585_lecture_slides/src
slides:
  - 00_ouverture/00_titre             # one page (its directory)
  - path: 00_ouverture/02_partie      # parameterized slide...
    title: Plan
    params: {current: 0}
  - 01_introduction                   # directory: all its pages, in file order
  - path: 00_ouverture/02_partie      # ...the same slide again, other parameters
    title: Transformations and rotations
    params: {current: 2}
  - 02_rotations/0[5-8]*              # glob on the page paths
  - 02_rotations                      # the rest of the section
  - path: 02_rotations/13_interpolation   # moved after the rest of the section
    title: Interpolation (summary)    # title in the menu
    duration: 1.5                     # minutes: the build log sums them
  - inf585:04_interpolation_position/content/07_hermite   # slide of another project
  - path: 03_squelette/10_bilan       # planned slide, no source yet
    title: Kinematics, summary
    message: IK = optimisation, FK = composition
  - '!*/00_section'                   # excluded, wherever it is listed
```

- A pointer is a path relative to the source directory: the directory of a
  page, a parent directory (all its pages, in file order, including its own
  page if it has one), a page file (`course/intro.html`, or `sec/index.html`
  for the page of a directory that also holds other pages), or a glob.
  Accented names match whatever the form the file system stores (Unicode
  NFC); `name:path` refers to another project only if `name` is one of the
  `sources` (otherwise it is a path). Hidden files and directories at the top
  level of a source (`.name`) are ignored, as they are not copied.
- A pointer that names a page (its directory or its file) takes precedence
  over parent directories and globs: the page is placed there, and skipped by
  the directories and globs.
- `!pattern` excludes the matching pages from the whole deck
  (`!inf585:*/00_title` for another project).
- A slide may be a mapping with `path` and metadata. `title` replaces the
  title in the menu; `duration` (minutes) is summed in the build log;
  `params` (see below); every other key (`message`, `notes`, ...) is exported
  in `structure.yaml`, like the page `config.yaml` (`structure.yaml` also gives
  the template of each page in the site, `template`, and its origin: `src`,
  its source file, `source`, `occurrence`). The metadata of a
  directory or a glob applies to each of its pages, except `duration`, which
  is the duration of all its pages together.
- Pages that are not in the deck are not generated (they are listed in the
  build log); the files of their directory (assets) are still copied, and
  their templates can still be included (`{% include 'parts/box.html.j2' %}`:
  Jinja reads the includes from the sources of the project, then of the other
  projects, then from the site).
- A pointer that matches no page is an error (with a suggestion), unless the
  slide has a `title`: it is a planned slide, reported in the log.
  `--scaffold` creates its source, `<path>/index.html.j2` (or `<file>.j2` for
  a pointer to a file), with the title and the other metadata as LHTML
  comments. Existing files are never modified; a planned directory is not
  created inside a directory that already holds pages (a pointer to a file,
  `sec/extra.html`, creates that file only).
- A deck that selects no page gives a warning.

**Other projects.** `sources` gives a name to the source directory of another
project (`name: path`); its pages are named `name:path`. They are generated
under `name/` in the site, with the files and asset directories of their
directory and their `config.yaml` (hidden files are not copied, and linked
directories are copied as directories). The name must not be a
directory of the project nor of the generator (`theme`, `structure`,
`sitemap`). The other project is only read: nothing is copied into its
sources or yours. A source must not contain the site. `--watch` also watches the deck file and, in the other
projects, the directories the deck points to. A page of another project is
rendered in this site: Jinja `extends`/`include` resolve from the sources of
the project, then from the root of the other projects, then from this site
(theme); LHTML `include::` from the page directory.

**Repeated slides and parameters.** Naming the same page explicitly again
creates another occurrence: it is generated next to the first one
(`index-2.html`, `index-3.html`, ..., skipping the names of the pages of
that directory, so that the names are the same in every build), so its relative assets still work, with
its own place in the navigation and its own metadata. The `params` of an
occurrence are given to Jinja as the variable `params` (empty for the other
pages; `params` is thus not a name for `keywords`), e.g. a plan that
highlights the current part:

```
{% set parts = ["Introduction", "Rotations", "Skeleton"] %}
{% set current = params.current | default(0) %}
div::[margin-left:600px;]
{%- for p in parts %}
* {% if loop.index == current %}**{{ p }}**{% else %}muted:: {{ p }} ::{% endif %}
{%- endfor %}
::
```

(The `{%-` remove the line breaks of the loop, which would otherwise split the
LHTML list.) Directories and globs never repeat a page: once a directory
holds several pages, name the file of the repeated one (`00_plan/index.html`);
an entry that places no page gives a warning.

The menu, the previous/next navigation, the redirection to the first page,
the PDF export and the layout report follow the deck. The sitemap ids
(`pathTo_<id>`, `linkTo_<id>`) are given to the pages of the project first,
so adding pages of other projects or repeated slides does not change them.
`--check-config` also reads the deck and the design (sources, macros). Several decks can share
the same sources (`python generate.py --deck deck_short.yaml`).

## Design: tokens, macros and layouts

A theme can describe its design in `design.yaml`: **tokens** (sizes, colors,
spacing), **macros** (LHTML tags such as `gap::`, `aside::`, `box::`) and
**layouts** of the pages. The `slides` and `slides-pdf` themes provide one,
built from the most frequent idioms of 904 existing slides.

```
= Inverse kinematics

aside::
img::assets/ik.png[width:450px;]
::

* Describe the position of the end effectors
gap::
* Compute the joint angles
gap::l
center::
videoplay::assets/ik.webm[width:750px;]
credit:: MiloScerny Animation ::
::
```

Macros of the slide themes: `gap::` (`gap::s`, `gap::l`, `gap::xl`),
`small::`, `tiny::`, `large::`, `credit::`, `muted::`, `center::`, `aside::`
(figure in the right column, `aside::[top:400px;]`), `cols::` / `col::`
(`.even`, `.spread`, `.middle`; `col::(.fixed)` keeps its width), `box::`
(`.good`, `.bad`, `.warn`, `.key`), `section::`, `demo::url` (iframe),
`placeholder:: text ::` (a planned figure), `intro::` (text above the columns of
`side`), `media::` (the figures of a layout: `.row`, `.even`, `.fill`,
`.top`/`.middle`/`.bottom`, `.auto`, `.here`).
Brackets still work for exceptions; the classes, style and attributes of
the source are added to those of the macro.

**Layouts.** A page chooses a layout with `{% set layout = 'side' %}` as its
first line (or `layout: side` in its `config.yaml` or its deck entry); the
theme then places and sizes its blocks, and `media::` holds its figures,
fitted in the area of the layout: no positions, widths or spacers to write.

```
{% set layout = 'side' %}
= Forward kinematics

* Each joint angle is set by hand
* Rotations are interpolated

media::
img::assets/fk.jpg
credit:: Image: Wikimedia Commons ::
::
```

Layouts of the slide themes (measured on 780 slides, they cover 68 % of
them; the others, text, text and code, columns, stay in the flow with the
macros):

| Layout | Page |
|--------|------|
| `side` (`side-s`, `side-l`) | Text on the left, figures in the right column below the title (36 % of the slides, also code + figure) |
| `stack` | Text, then figures taking the rest of the slide; `media::(.row)` for a row of figures (21 %) |
| `section` | Section or title slide, centered (11 %) |

A layout is a class of `<body>` (`layout-side`, plus `layout-side-s` for a
variant) styled by its `css` in `design.yaml` (`layouts:` with `css` and
`doc`, documented in `structure/design.md`); the `design` key adds or
removes layouts like macros.

**Lint.** `python generate.py --lint` lists the values written by hand in the
pages, including those not in the deck, with what replaces them in the
design: positions (`position:fixed`, `top`, `left`), spacers
(`div::[height:25px;]::` → `gap::`), font sizes in percent (→ `small::`,
`tiny::`, `large::`), line heights, offsets in pixels (except the documented
ones of `aside::`), `display:flex` (→ `cols::`), `text-align:center`
(→ `center::`), gray text (→ `muted::`), `display:none` (→ `(.hidden)`), an
`<iframe>` written by hand (→ `demo::`), sizes of figures in a page with a
layout (→ `media::`), and unknown layouts or layouts without `media::`:

```
src/03_squelette/04_ik/index.html.j2:9: spacer: div::[height:25px;]::
    -> gap::
```

Each build gives their number (the style debt of the deck), and the layout
report lists them per page (column `lint` of `summary.md`). Code blocks are
not linted; a value that nothing in the design covers (an annotation drawn
over a figure) can stay.

The generator:

1. merges the theme's `design.yaml` with the `design` key of the
   configuration (a value `null` removes a token or a macro),
2. writes `theme/css/design.css`: the tokens as CSS variables
   (`font: {small: 85%}` gives `--font-small`), then the `css` of each macro,
3. writes their reference in `structure/design.md` of the site (macros,
   layouts, tokens: for authors and LLMs; the layout report links to it),
4. validates the tokens and the macros (with LHTML), and gives the macros to LHTML without their `css`.

A design file may start from another one with `extends` (relative to the
file), then override it key by key; `slides-pdf` reuses the design of
`slides` this way:

```yaml
extends: ../slides/design.yaml
tokens:
  font: {small: 80%}
```

Change the look of a whole deck in `configure.yaml`:

```yaml
design:
  tokens:
    space: {m: 30px}                 # gap::
    aside: {top: 180px, right: 80px} # aside::
    section: {top: 250px}
  macros:
    note:                            # new macro: note:: text ::
      class: note
      css: '.note { color: var(--color-muted); font-style: italic; }'
      doc: 'Side remark. note:: text ::'
    demo: null                       # remove a macro of the theme
```

Macro fields (see the LHTML README): `tag` (default `div`), `class`, `style`,
`attrs`, `empty`, `url`, `variant`, `default`, plus `css` and `doc` used by
the generator. The `design` key may also be the path of a YAML file with
the same structure.

## Credits, origin of the slides, figures in code

**Credits.** A page declares the credits of its images in its `config.yaml`
(or deck entry), and its `origin` (the slide it was copied from):

```yaml
origin: csc_43043/course_slides/src/08_transformations/02_rotation/01_definition
credits:
  assets/euler.jpg:
    author: J. E. Handmann, 1753
    source: Wikimedia Commons
    license: public domain
    url: https://commons.wikimedia.org/wiki/File:...
  assets/plaque.jpg: Brendan Ward, CC0      # a text is the whole credit
```

In the page, `credit:: {{ credit('assets/euler.jpg') }} ::` writes the
caption from it ("J. E. Handmann, 1753, Wikimedia Commons, public domain"; an
error if the file has no credit), and `credits` lists the credits of all the
pages, for a credits slide:

```
= Credits
small::
{%- for c in credits %}
* {{ c.title }}: {{ c.text }}
{%- endfor %}
::
```

Each build writes `structure/credits.md`: the origin of each page (`origin`,
or its project), the credits, and the images and videos used by the pages
without credit (to check: your own figures need none).

**To do.** `placeholder:: video of the walk cycle ::` draws a planned figure;
each build lists the planned figures (with their line) and the planned slides
of the deck in `structure/todo.md`, and gives their number in the log.

**Figures in code.** A file `<name>.<format>.py` of the sources (`svg`, `png`,
`pdf`, `jpg`), e.g. `assets/curve.svg.py`, is a script that writes the figure
`assets/curve.svg`: it gets the file to write as its argument and runs in its
directory, with the Python of the generator (install what it imports, e.g.
matplotlib). `<name>.svg.tex` is a standalone LaTeX document (TikZ) made into
SVG with `latex` and `dvisvgm`. The page uses the figure as any other
(`img::assets/curve.svg`). Figures are made in the site, never in the
sources, and kept in `.figures/` next to the configuration under the hash of
their script: a figure is made again when its script changes (delete
`.figures/` after a change of the data it reads). A figure that fails gives a
warning with the error.

## Plugins

Plugins are Python files with optional hooks:

```python
def pre_process(meta):   # Before Jinja2 rendering
    ...

def mid_process(meta):   # Between Jinja2 and LHTML
    ...

def post_process(meta):  # After all conversions
    ...
```

Each hook still receives a real mutable `meta` dictionary with configuration and runtime state. Internally, `Config` holds the resolved user settings, and `BuildContext` creates an independent copy for plugins and generation. Plugin changes (including nested `keywords` changes and generated heading IDs) do not alter the original configuration. Existing hook signatures and dictionary access remain supported.

With `title_submenu.py`, each page exports its own `<filename>.title_id.json` (for example `index.html.title_id.json`). The bundled theme reads the current page's file. `structure/title_id.json` is indexed by relative HTML page path. A legacy `title_id.json` is also written for directory indexes or single-page folders; custom themes with multiple pages per folder should use the per-page files.

Page-level `config.yaml` files may be empty or contain only comments. Their metadata must otherwise be a mapping. Template discovery has no default depth limit, skips directory symlink cycles and never enters the site (reached through a link). The generator never writes through a link into the sources or the theme: a symbolic link to a directory is copied into the site as a directory (a linked library of videos is thus copied into each build), and a link to a file is kept only if it is relative and leads to a file of the copy, else the file is copied. A link to a directory containing it is kept only if it is relative and stays in the sources; the site itself is never copied.

Plugins get the pages from `lib.structure`: `structure(meta)` gives all the pages of the site, in order (the entries of `structure/structure.yaml`), and `built_pages(meta)` the pages generated by this build (all of them, or those of `--only`). A plugin working on the pages (templates, HTML) uses `built_pages`; one writing a file for the whole site (menu, redirection) uses `structure`. `template_path(meta, entry)` gives the template of a page in the site, for the pre-process hooks. The keys written by the generator (`dir`, `filename`, `template`, `level`, `src`, `source`, `occurrence`, `path`, `title_id`) cannot be set in a `config.yaml` nor in the deck.

### Built-in Plugins

| Plugin | Hook | Description |
|--------|------|-------------|
| `auto_wrap.py` | pre | Wraps plain HTML files in Jinja2 template structure |
| `title_submenu.py` | pre | Generates IDs for headings, exports navigation JSON |
| `menu.py` | post | Injects sitemap structure into the JS menu |
| `redirection_first_page.py` | post | Creates `index.html` redirect to first page |
| `pre_include.py` | pre | Pre-includes content files into templates |
| `code_include.py` | mid | Includes code snippets from external Git repos |
| `cache_video.py` | pre | Converts and caches videos in multiple codecs |
| `layout_report.py` | post | Layout report of each page (`--layout`, requires `npm install`) |
| `generate_pdf.py` | pre+post | Generates PDF slides and images (requires `npm install`, see Installation; put it last) |

## Layout Report (LLM-assisted slide layout)

`--layout` measures the layout of every generated page in headless Chrome and
writes a text report that an LLM (or any script) can read to find and fix
layout problems. It requires `npm install` (see Installation).

```bash
python generate.py --layout          # full generation + layout report
python generate.py --only 03_squelette/04_ik --layout   # after editing a slide
```

The measure shows its progress (pages measured, time left). With `--only`,
only those pages are measured, and the summary keeps the other pages of the
previous report. Output in `.layout/` (next to the configuration file). Each page has a unique `pages/<relative HTML path>/` directory, for example `pages/chapter/a.html/layout.json`. The output path remains configurable and is checked before deletion: it cannot overlap sources, theme, site or cache, or contain the configuration, generator or plugin files. Paths through symbolic links are checked too.

Files:

- `summary.md`: the usual values of the deck (its style, see below), then all
  pages sorted by number of problems and warnings, with their number `n` in
  the deck and links to the page reports
- `contact_NN.png` (and `.html`): thumbnails of all pages in deck order, 16
  per sheet, with badges `P` (problems), `W` (warnings), `D` (differences
  with the deck): the whole deck at a glance
- `deck.json`: the usual values of the deck, for scripts
- `changes.md`: what changed since the previous report (see below)
- `summary.md` links to `structure/design.md` of the site: the macros and
  tokens of the design (when the theme or the configuration defines one), to
  use instead of inline styles
- `pages/<relative HTML path>/layout.md`: one row per top-level block (number, kind, position and
  size of what is actually drawn, margins, CSS position, font size, signature),
  then the problems, warnings, differences with the deck, density and the
  vertical gaps between blocks
- `pages/<relative HTML path>/layout.json`: the same data, for scripts
- `pages/<relative HTML path>/render.png`: the real render
- `pages/<relative HTML path>/overlay.png`: the real render with the outlined ink of each block and its number
- `pages/<relative HTML path>/blocks.png`: the ink of each block as solid rectangles, content hidden

Coordinates are CSS pixels, origin at the top-left corner of the page
(1920×1080 for slides); the usable area is the inside of the slide frame.
Detected problems:

- `HIDDEN TEXT`: text covered by another block drawn on top of it (checked in
  the browser, along each line of text: an opaque image pixel or a background
  of another block is visible on top of the text)
- `COLLISION`: the drawn content of two blocks overlaps (text on text, text
  on the drawn part of an image, images, backgrounds)
- `OUT OF AREA`: block beyond the usable area
- `CLIPPED`: content cut by `overflow`
- `UPSCALED IMAGE`: bitmap or video drawn more than 1.25× its native size,
  hence blurry (vector images such as SVG are ignored)
- `RESERVED AREA`: content over an area of the theme (the navigation: the
  elements of `exclude`)

Warnings:

- `TIGHT`: the line box of a text overlaps another text or an image by less
  than 0.4× the font size: the glyphs usually do not touch, but the spacing
  is tight. Text on the background of another block is not an overlap (only
  hidden text matters there).
- `NEAR-ALIGNED`: an edge or the center of a block is 3 to 12 px away from
  that of another block, of the usable area, or of a column of the deck:
  align it exactly, or move it clearly. Only edges whose position is
  meaningful are compared: edges of images filling their box and of
  backgrounds/borders, the aligned side of text (left, right or center,
  from `text-align`); tops and bottoms only between blocks side by side.
- `DENSE` (more than `max_words` words of text) and `SMALL FONT` (text
  smaller than `min_font` px), on slides only.
- `WRAPPED`: a title on several lines, or a list item (or credit) whose
  second line holds only a few words.
- `ROW`: figures side by side whose tops (or bottoms) differ by 3 to 40 px.
- `SMALL IN ITS BOX` / `CROPPED`: a figure drawn on less than 75 % of its
  box, or cut, by `object-fit` (e.g. in `media::`: use `media::(.fill)` or
  another arrangement).

Each page report also gives its density: words (math and code excluded),
formulas, lines of code, list items, lines of text, smallest font size, the
parts of the area covered by text and images, and the largest free area.

Renders are reproducible: videos are measured at their first frame, animated
GIFs at their first image, CSS animations stopped. `changes.md` lists what
changed since the previous report for the pages measured again: counts of
problems, warnings and values written by hand, blocks moved or resized
(matched by their signature), added or removed.

Differences with the deck: the usual values of the deck are measured over
all its pages (`summary.md`, `deck.json`): page title variants (heading tag
and font size used on at least 3 pages) with their position (left edge or
center, top or middle: whichever varies least), columns (left edges of
in-flow blocks shared by at least a quarter of the pages), body font size
and the text sizes used on several pages, gap below the title, words per
page and occupancy. A page is compared with them: `TITLE POSITION`,
`TITLE VARIANT` (title of an unusual kind or size), `TITLE GAP`, `TEXT FONT`
(text in a size used nowhere else). These are not errors, but breaks of
consistency to check.

Only what is actually drawn counts (the *ink* of a block): text lines, images
reduced to their drawn shape (16 px cells; uniform or transparent background
removed), backgrounds and borders. Each block is described by a list of typed
ink rectangles (`"ink"` in `layout.json`), so invisible full-width boxes and
the empty corners of an irregular block do not create collisions. Empty
blocks (`::nl`, `div[height:...]`) are `spacer`s and are ignored.

An overlap can be intentional (zoom inset over an image, annotation placed on
a figure): add the class `overlay` to one of the blocks, e.g.
`::(.overlay)[position:fixed; ...]`. The overlap is then listed in the
`Notes` section instead of the problems (hidden text is still reported).

A block is a top-level element of the page: title, paragraph or bare text,
list, code block, image, video, math, or a `div::` / `::[...]` with all its
content. An element placed out of the flow (`position: fixed` or `absolute`)
inside a block is measured as a block of its own (`in #n` in the table), so
that it collides with the text of its block. Each block gives the line of the
source where it starts (column `line`, from the source map below), and its
signature (tag, inline style, beginning of the text, image names).

**Source map.** In the builds for development (`--layout`, `--serve`,
`--watch`), the top-level elements of the pages carry
`data-src="<file>:<line>"`: the line of the template where they start. The
generator marks the lines of the templates with invisible characters before
Jinja and LHTML, then moves them to the attribute (`lib/source_map.py`); the
HTML is otherwise the same as in a normal build.

Typical loop with an LLM (e.g. Claude Code): "read `.layout/summary.md` and
the contact sheets, fix the collisions and overflows by editing the sources
(positions, widths, font sizes), run `python generate.py --only <slide> --layout` and
check the new report".

Options (`configure.yaml`):

```yaml
plugin_arg:
  layout_report:
    root: 'body'                # content root ('#main-content-centered' for webpage-frame)
    exclude: 'nav, footer'      # children of the root that are not content
    width: 1920                 # viewport size
    height: 1080
    images: true                # write render.png / overlay.png / blocks.png and contact sheets
    threshold: 4                # minimal overlap / overflow reported (px)
    output: '.layout/'
    max_words: 80               # DENSE above this number of words per slide
    min_font: 20                # SMALL FONT below this font size (px)
    contact_columns: 4          # thumbnails per row and rows per contact sheet
    contact_rows: 4
```

## Style Profile (writing slides in the style of an author)

`tools/style_profile.py` describes what the slides of a corpus usually look
like and how they are written, so that an LLM can write new slides in the
same style:

```bash
python tools/style_profile.py ../course_a ../course_b --output style/
```

Each argument is a slide project with `src/<chapter>/` and the generated
`_site/<chapter>/html/` (nothing is regenerated: the pages are measured as
they are, like `--layout`). Measurements are cached in `style/pages/` and
redone only for pages generated since (`-f` to force, `-j` for the number of
browsers in parallel). A slide copied in several chapters counts once.

Output:

- `style.md`: usual values of each deck (title, columns, font sizes, words
  per slide), layout types of the slides (`section`, `media`, `media_row`,
  `columns`, `text_left_media_right`, `text_then_media`, `text_code`,
  `code_media`, `text`, ...) with their frequency in each deck, typical
  measures and examples (path and LHTML source), and the LHTML idioms of
  the sources (block tags, spacers, most used style properties and values,
  most frequent block openers)
- `types/<type>.png`: thumbnails of 16 examples of each layout type
- `style.json`: the same data, with the type and measures of every slide

## Error Reporting

Errors during LHTML conversion show the file path and line number:

```
[Error] .site/content/page/index.html: line 42: Position 156: Unclosed bracket '[' (expected ']')
```

Errors are non-fatal — the generator continues processing remaining files (a page whose Jinja2 rendering fails is skipped), then exits with code 1 if any page or plugin failed (missing plugin, exception in a plugin; use `-d` to see the traceback). Errors of the deck start with `Deck:` and errors of the design with `Design:`.

## Migrating from the previous layout

- `configure_default.yaml` is now `configure_example.yaml`. The old filename falls back to the new file with a warning if the old file is absent.
- Replace `plugin_post` with `plugin`. The old key is accepted with a warning and selects plugins whose available hooks run at each stage. Specifying both keys is an error.
- `.site/` is the output default; an explicit `site_directory` still takes precedence.

- LHTML is now installed with pip (`lhtml-markup`, see `requirements.txt`) instead of the `lib/lhtml` submodule.
- `theme_templates/` was renamed `themes/` and `src_site_example/` was renamed `example/`. Configuration files that still use the old paths keep working (with a warning); update them, e.g. `theme: 'static_website_lhtml/themes/webpage-frame/'`.
- Light mode (`-l`) was removed: it copied the whole previous site and was not faster than a full build. Use `--only <page>` to regenerate some pages.
- Deck parameters of a page are read as `params.<name>` (not as top-level variables).
- `plugins/auto-wrap.py` was renamed `plugins/auto_wrap.py` (the old name keeps working, with a warning).
- Heading anchors generated by `title_submenu.py` keep the same scheme as before. Two bugs are fixed: identical headings, or a heading that starts like another one (`= Installation` / `== Installation sous Windows`), now get distinct ids, and characters such as `<`, `>`, `"` are removed from ids.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

Development dependencies are listed separately in `requirements-dev.txt` and share the version lock. The tests require Node.js to validate generated menu JavaScript and the heading reader. The suite covers configuration precedence, validation, path protection, read-only diagnostics, plugin context isolation, generation regressions, and simulated PDF tool failures.

The GitHub Actions workflow runs on pushes and pull requests, on Python 3.11 and 3.14 with Node.js 22. It runs the suite and real Chrome/HTTP smoke tests. Run these locally after `npm ci`:

```bash
LHTML_BROWSER_TEST=1 LHTML_PREVIEW_TEST=1 python -m pytest tests/test_layout_integration.py tests/test_development.py -q
```

The browser and HTTP tests are opt-in locally because they launch Chrome and bind a localhost port. When updating dependencies, update `requirements-lock.txt`, install into a fresh environment, and run both the unit suite and smoke tests before committing. Optional PDF/SASS system tools are not part of the Python lock.

## License

MIT
