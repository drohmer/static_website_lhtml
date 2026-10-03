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
python generate.py [-i config.yaml] [-d | --no-debug] [-c] [-l] [--check-config]

  -i, --input_config   YAML configuration file (default: configure.yaml)
  -d, --debug          Display debug info and keep temporary files
      --no-debug       Override debug: true from YAML
      --check-config   Validate paths and plugin files; display resolved settings
  -c, --clean          Remove only the configured output directory and exit
  -l, --light          Light mode: only convert .html.j2 files (skip asset copy)
```

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
| `generate_pdf.py` | pre+post | Generates PDF slides and images (requires `npm install`, see Installation; put it last) |

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
python -m unittest discover -s tests -v
```

The tests require Node.js to validate generated menu JavaScript and the heading reader. The suite covers configuration precedence, validation, path protection, read-only diagnostics, plugin context isolation, generation regressions, and simulated PDF tool failures.

## License

MIT
