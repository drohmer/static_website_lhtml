# Static Website LHTML

A static site generator built on [LHTML](https://github.com/drohmer/lhtml) and Jinja2. Transforms template sources (`.html.j2` with LHTML markup) into a complete static website.

## Installation

```bash
git clone https://github.com/drohmer/static_website_lhtml.git
cd static_website_lhtml
pip install -r requirements.txt
```

**Python**: 3.11 or newer. Runtime and transitive dependencies are pinned in `requirements-lock.txt`; `requirements.txt` applies these constraints. Use `npm ci` to install the locked Node dependencies.

**Dependencies**: `lhtml-markup`, `Jinja2`, `jinja-markdown`, `pytidylib`, `pyyaml`, `rich`

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
python generate.py [-i config.yaml] [-d | --no-debug] [-c] [-l] [--check-config] [--layout] [--deck FILE] [--scaffold] [--serve] [--watch] [--port PORT]

  -i, --input_config   YAML configuration file (default: configure.yaml)
  -d, --debug          Display debug info and keep temporary files
      --no-debug       Override debug: true from YAML
      --check-config   Validate paths and plugin files; display resolved settings
  -c, --clean          Remove only the configured output directory and exit
  -l, --light          Light mode: only convert .html.j2 files (skip asset copy)
  --serve              Serve the generated site on http://127.0.0.1:8000/
  --watch              Rebuild after source, theme, plugin or configuration edits
  --port PORT          HTTP port (default: 8000; 0 selects an available port)
  --layout             Write a layout report of each page in .layout/ (see below)
  --deck FILE          Order of the slides: deck file replacing the 'deck' of the configuration
  --scaffold           Create the source of the deck slides that do not exist yet
```

## Local preview

```bash
python generate.py --serve --watch
```

The server binds only to localhost. Open the printed URL, and refresh the browser after a rebuild. `--serve` can be used alone; `--watch` can rebuild without an HTTP server. Stop with Ctrl+C. The watcher polls inputs and waits for saves to settle. It watches the source, theme, YAML configuration, deck and design files, configured plugin files and `pre_include` files. It does not follow directory symlinks or watch remote repositories. Use full builds with `--watch` (it cannot be combined with `--light`). Changes to assets and configuration are included. Invalid edits leave the previous site available, and a later edit retries the build.

Complete and light builds run in a hidden temporary sibling directory. Only a successful build replaces the output; failures preserve the previous site. Light mode copies the existing output into staging to retain its assets. With `--debug`, failed staging directories are kept and their location is reported. Publication uses a backup/rename with rollback on failure; there is a brief directory swap, not an atomic filesystem exchange. Plugin side effects outside the site directory (reports, PDF, caches or custom actions) are not covered by the site transaction. PDF-only exports can remove their staged HTML on success; an existing published site is retained.

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
| `deck` | Order of the pages: path of a deck file, or list of slides (see [Deck](#deck-order-of-the-slides)); without deck, the order of the files |
| `design` | Tokens and macros overriding the theme's `design.yaml` (mapping, or path of a YAML file; see [Design](#design-tokens-and-macros)) |

## Pipeline

The generator runs the following stages:

1. **Data preparation** — Copy sources and theme to `.site/`, find `.html.j2` templates, extract metadata and sitemap
2. **Pre-process plugins** — Plugin hooks before Jinja2 rendering
3. **Jinja2 rendering** — Render all `.html.j2` templates with variables (sitemap links, keywords, etc.)
4. **Mid-process plugins** — Plugin hooks between Jinja2 and LHTML
5. **LHTML conversion** — Convert LHTML markup to HTML, with optional tidy
6. **SASS compilation** — Compile `.sass` files to `.css` (if libsass installed)
7. **Post-process plugins** — Plugin hooks after all conversions

## Project Structure

```
static_website_lhtml/
  generate.py              # Main generator
  configure_example.yaml   # Commented example configuration
  requirements.txt
  lib/
    configuration.py       # Validated Config and BuildContext plugin adapter
    deck.py                # Deck: order of the slides (deck.yaml)
    design.py              # Design tokens and macros (design.yaml -> design.css)
    filesystem.py          # File/directory utilities
    generator_tool.py      # Metadata extraction, sitemap generation
    logger.py              # Console output (rich)
    structure.py           # Shared load_structure() for plugins
  plugins/
    auto_wrap.py           # Auto-wrap plain HTML in Jinja2 template
    menu.py                # Generate JS menu from sitemap
    redirection_first_page.py  # Create index.html redirect
    title_submenu.py       # Extract heading IDs for navigation
    pre_include.py         # Pre-include content into templates
    code_include.py        # Include code from external repos
    cache_video.py         # Video codec conversion and caching
    generate_pdf.py        # PDF/image generation (requires puppeteer)
    video_convert/         # Video conversion utilities (ffmpeg)
  themes/
    webpage-frame/         # Default web page theme
    slides/                # Presentation slides theme
    slides-pdf/            # PDF export slides theme
  example/                 # Example source content
```

## Themes

Three built-in themes are available:

- **`webpage-frame/`** — Standard website with navigation menu, suitable for documentation and course pages
- **`slides/`** — Presentation slides for browser display
- **`slides-pdf/`** — Presentation slides optimized for PDF export

Themes use Jinja2 template inheritance. The base template (`template/base.html`) provides blocks that content pages can override.

## Deck: order of the slides

Without a deck, the pages are generated in the order of the files (sorted
paths, hence numbered directories such as `02_rotations/04_representations`).
A deck lists the slides with pointers to their sources, so that the order
does not depend on the names of the directories:

```yaml
# deck.yaml (configure.yaml: deck: 'deck.yaml')
title: Talk, short version
slides:
  - 00_ouverture                      # directory: all its pages, in file order
  - 02_rotations/00_section           # one page (its directory)
  - 02_rotations/0[5-8]*              # glob on the page paths
  - 02_rotations                      # the rest of the section
  - path: 02_rotations/13_interpolation   # moved after the rest of the section
    title: Interpolation (summary)    # title in the menu
    duration: 1.5                     # minutes: the build log sums them
  - path: 03_squelette/10_bilan       # planned slide, no source yet
    title: Kinematics, summary
    message: IK = optimisation, FK = composition
  - '!06_recherche/*_todo_*'          # excluded, wherever it is listed
  - '!*/00b_histoire'
```

- A pointer is a path relative to the source directory: the directory of a
  page, a parent directory (all its pages, in file order), a page file
  (`course/intro.html`, when a directory holds several pages), or a glob.
- A pointer that names exactly one page takes precedence over directories and
  globs: the page is placed there, and skipped by the directories and globs.
  The same page named twice keeps its first place (with a warning).
- `!pattern` excludes the matching pages from the whole deck.
- A slide may be a mapping with `path` and metadata. `title` replaces the
  title in the menu; `duration` (minutes) is summed in the build log; every
  other key (`message`, `notes`, ...) is exported in `structure.yaml`, like
  the page `config.yaml`. The metadata of a directory or a glob applies to
  each of its pages.
- Pages that are not in the deck are not generated (they are listed in the
  build log); the files of their directory (assets) are still copied.
- A pointer that matches no page is an error (with a suggestion), unless the
  slide has a `title`: it is a planned slide, reported in the log.
  `--scaffold` creates its source, `<path>/index.html.j2`, with the title and
  the other metadata as LHTML comments (existing files are never modified).

The menu, the previous/next navigation, the redirection to the first page,
the PDF export and the layout report follow the deck. Several decks can share
the same sources (`python generate.py --deck deck_short.yaml`).

## Design: tokens and macros

A theme can describe its design in `design.yaml`: **tokens** (sizes, colors,
spacing) and **macros** (LHTML tags such as `gap::`, `aside::`, `box::`). The
`slides` and `slides-pdf` themes provide one, built from the most frequent
idioms of 904 existing slides. Macros require `lhtml-markup` 2.5 or later.

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
`small::`, `tiny::`, `credit::`, `muted::`, `center::`, `aside::` (figure in
the right column, `aside::[top:400px;]`), `cols::` / `col::` (`.even`,
`.spread`, `.middle`), `box::` (`.good`, `.bad`, `.warn`), `section::`,
`demo::url` (iframe). Brackets still work for exceptions; the classes, style
and attributes of the source are added to those of the macro.

The generator:

1. merges the theme's `design.yaml` with the `design` key of the
   configuration (a value `null` removes a token or a macro),
2. writes `theme/css/design.css`: the tokens as CSS variables
   (`font: {small: 85%}` gives `--font-small`), then the `css` of each macro,
3. gives the macros to LHTML,
4. with `--layout`, writes their reference in `.layout/design.md` (for authors
   and LLMs).

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

Page-level `config.yaml` files may be empty or contain only comments. Their metadata must otherwise be a mapping. Template discovery has no default depth limit and skips directory symlink cycles.

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
python generate.py -l --layout       # after editing a slide: light mode + report
```

Output in `.layout/` (next to the configuration file). Each page has a unique `pages/<relative HTML path>/` directory, for example `pages/chapter/a.html/layout.json`. The output path remains configurable and is checked before deletion: it cannot overlap sources, theme, site or cache, or contain the configuration, generator or plugin files. Paths through symbolic links are checked too.

Files:

- `summary.md`: the usual values of the deck (its style, see below), then all
  pages sorted by number of problems and warnings, with their number `n` in
  the deck and links to the page reports
- `contact_NN.png` (and `.html`): thumbnails of all pages in deck order, 16
  per sheet, with badges `P` (problems), `W` (warnings), `D` (differences
  with the deck): the whole deck at a glance
- `deck.json`: the usual values of the deck, for scripts
- `design.md`: the macros and tokens of the design (when the theme or the
  configuration defines one), to use instead of inline styles
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
- `UPSCALED IMAGE`: bitmap displayed more than 1.25× its native size, hence
  blurry (vector images such as SVG are ignored)

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

Each page report also gives its density: words (math and code excluded),
formulas, lines of code, list items, lines of text, smallest font size, and
the parts of the area covered by text and images.

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
content. Its signature (tag, inline style, beginning of the text, image names)
is enough to find it in `src/.../index.html.j2`.

Typical loop with an LLM (e.g. Claude Code): "read `.layout/summary.md` and
the contact sheets, fix the collisions and overflows by editing the sources
(positions, widths, font sizes), run `python generate.py -l --layout` and
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

Errors are non-fatal — the generator continues processing remaining files (a page whose Jinja2 rendering fails is skipped), then exits with code 1 if any page or plugin failed (missing plugin, exception in a plugin; use `-d` to see the traceback).

## Migrating from the previous layout

- `configure_default.yaml` is now `configure_example.yaml`. The old filename falls back to the new file with a warning if the old file is absent.
- Replace `plugin_post` with `plugin`. The old key is accepted with a warning and selects plugins whose available hooks run at each stage. Specifying both keys is an error.
- `.site/` is the output default; an explicit `site_directory` still takes precedence.

- LHTML is now installed with pip (`lhtml-markup`, see `requirements.txt`) instead of the `lib/lhtml` submodule.
- `theme_templates/` was renamed `themes/` and `src_site_example/` was renamed `example/`. Configuration files that still use the old paths keep working (with a warning); update them, e.g. `theme: 'static_website_lhtml/themes/webpage-frame/'`.
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
