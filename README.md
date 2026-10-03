# Static Website LHTML

A static site generator built on [LHTML](https://github.com/drohmer/lhtml) and Jinja2. Transforms template sources (`.html.j2` with LHTML markup) into a complete static website.

## Installation

```bash
git clone https://github.com/drohmer/static_website_lhtml.git
cd static_website_lhtml
pip install -r requirements.txt
```

**Dependencies**: `lhtml-markup`, `Jinja2`, `jinja-markdown`, `pytidylib`, `pyyaml`, `rich`

Optional:
- **PDF export** (`generate_pdf.py`): Node.js, then `npm install` in this directory (installs `puppeteer`, which downloads a headless Chrome, and `minimist`, see `package.json`), plus `pdfunite`/`pdftoppm` (poppler) and ImageMagick (`magick`) for the slide images. Put `generate_pdf.py` last in the plugin list: after the export, it removes the site directory (kept with `-d`).
- **SASS**: `pip install libsass` to compile `.sass` files (a warning is shown if they are left uncompiled).

## Quick Start

```bash
python generate.py -i configure_default.yaml
```

This generates a site from `example/` into `_site/` using the default theme.

For your own project, copy and edit the config:

```bash
cp configure_default.yaml configure.yaml
# Edit configure.yaml with your source/theme paths
python generate.py
```

## CLI Options

```
python generate.py [-i config.yaml] [-d] [-c] [-l] [--layout]

  -i, --input_config   YAML configuration file (default: configure.yaml)
  -d, --debug          Display debug info and keep temporary files
  -c, --clean          Clean output directories and exit
  -l, --light          Light mode: only convert .html.j2 files (skip asset copy)
  --layout             Write a layout report of each page in _layout/ (see below)
```

## Configuration

```yaml
source_directory: 'example/'           # Source content directory
site_directory: '_site/'               # Output directory
theme: 'themes/webpage-frame/'         # Theme directory
plugin:                                # Plugin list (executed in order)
  - 'plugins/menu.py'
  - 'plugins/redirection_first_page.py'
```

Optional keys:

| Key | Description |
|-----|-------------|
| `cache_video_directory` | Directory for cached video codec conversions |
| `use_tidy` | Enable HTML tidy post-processing (default: false) |
| `keywords` | Extra Jinja2 template variables |
| `plugin_arg` | Arguments passed to specific plugins |
| `title_id` | Generate heading IDs (default: true) |

## Pipeline

The generator runs the following stages:

1. **Data preparation** — Copy sources and theme to `_site/`, find `.html.j2` templates, extract metadata and sitemap
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
  configure_default.yaml   # Default configuration
  requirements.txt
  lib/
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

Each hook receives the `meta` dict with the full configuration and runtime state.

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

Output in `_layout/` (next to the configuration file):

- `summary.md`: all pages sorted by number of problems, with links to the page reports
- `<page>/layout.md`: one row per top-level block (number, kind, position and
  size of what is actually drawn, margins, CSS position, font size, signature),
  then the problems and the vertical gaps between blocks
- `<page>/layout.json`: the same data, for scripts
- `<page>/overlay.png`: the real render with the outlined ink of each block and its number
- `<page>/blocks.png`: the ink of each block as solid rectangles, content hidden

Coordinates are CSS pixels, origin at the top-left corner of the page
(1920×1080 for slides); the usable area is the inside of the slide frame.
Detected problems: `COLLISION` (two blocks overlapping, with the overlap
rectangle), `OUT OF AREA` (block beyond the frame), `CLIPPED` (content cut by
`overflow`), `UPSCALED IMAGE` (image displayed larger than its native size).

Only what is actually drawn counts (the *ink* of a block): text lines, images
trimmed to their drawn content (uniform or transparent background removed),
backgrounds and borders. Each block is described by a list of ink rectangles
(`"ink"` in `layout.json`), so invisible full-width boxes and the empty corners
of an irregular block (short last lines, L-shaped content) do not create
collisions. A block that overlaps only the background of an image is listed in
a `Notes` section, not as a problem. Empty blocks (`::nl`, `div[height:...]`)
are `spacer`s and are ignored by the analysis.

A block is a top-level element of the page: title, paragraph or bare text,
list, code block, image, video, math, or a `div::` / `::[...]` with all its
content. Its signature (tag, inline style, beginning of the text, image names)
is enough to find it in `src/.../index.html.j2`.

Typical loop with an LLM (e.g. Claude Code): "read `_layout/summary.md`, fix
the collisions and overflows by editing the sources (positions, widths, font
sizes), run `python generate.py -l --layout` and check the new report".

Options (`configure.yaml`):

```yaml
plugin_arg:
  layout_report:
    root: 'body'                # content root ('#main-content-centered' for webpage-frame)
    exclude: 'nav, footer'      # children of the root that are not content
    width: 1920                 # viewport size
    height: 1080
    images: true                # write overlay.png / blocks.png
    threshold: 4                # minimal overlap / overflow reported (px)
    output: '_layout/'
```

## Error Reporting

Errors during LHTML conversion show the file path and line number:

```
[Error] _site/content/page/index.html: line 42: Position 156: Unclosed bracket '[' (expected ']')
```

Errors are non-fatal — the generator continues processing remaining files (a page whose Jinja2 rendering fails is skipped), then exits with code 1 if any page or plugin failed (missing plugin, exception in a plugin; use `-d` to see the traceback).

## Migrating from the previous layout

- LHTML is now installed with pip (`lhtml-markup`, see `requirements.txt`) instead of the `lib/lhtml` submodule.
- `theme_templates/` was renamed `themes/` and `src_site_example/` was renamed `example/`. Configuration files that still use the old paths keep working (with a warning); update them, e.g. `theme: 'static_website_lhtml/themes/webpage-frame/'`.
- `plugins/auto-wrap.py` was renamed `plugins/auto_wrap.py` (the old name keeps working, with a warning).
- Heading anchors generated by `title_submenu.py` keep the same scheme as before. Two bugs are fixed: identical headings, or a heading that starts like another one (`= Installation` / `== Installation sous Windows`), now get distinct ids, and characters such as `<`, `>`, `"` are removed from ids.

## License

MIT
