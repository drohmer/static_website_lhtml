# Static Website LHTML

A static site generator built on [LHTML](https://github.com/drohmer/lhtml) and Jinja2. Transforms template sources (`.html.j2` with LHTML markup) into a complete static website.

## Installation

```bash
git clone https://github.com/drohmer/static_website_lhtml.git
cd static_website_lhtml
pip install -r requirements.txt
```

**Dependencies**: `lhtml-markup`, `Jinja2`, `jinja-markdown`, `pytidylib`, `pyyaml`, `rich`

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
python generate.py [-i config.yaml] [-d] [-c] [-l]

  -i, --input_config   YAML configuration file (default: configure.yaml)
  -d, --debug          Display debug info and keep temporary files
  -c, --clean          Clean output directories and exit
  -l, --light          Light mode: only convert .html.j2 files (skip asset copy)
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
| `generate_pdf.py` | pre+post | Generates PDF slides and images (requires puppeteer) |

## Error Reporting

Errors during LHTML conversion show the file path and line number:

```
[Error] _site/content/page/index.html: line 42: Position 156: Unclosed bracket '[' (expected ']')
```

Errors are non-fatal — the generator continues processing remaining files.

## License

MIT
