"""Static website generator built on LHTML.

Pipeline: copy sources → Jinja2 rendering → LHTML conversion → SASS compilation
with plugin hooks at pre/mid/post stages.
"""

from jinja2 import Environment, FileSystemLoader
import tidylib
import yaml
import os
import shutil
import argparse
import sys
import importlib.util
import platform
import copy
import traceback

from lib import filesystem
from lib import generator_tool
from lib import logger

import lhtml


# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

META_DEFAULTS = {
    'source_directory': 'src_site/',
    'site_directory': '_site',
    'theme': 'themes/webpage-frame/',
    'config_file': 'configure.yaml',
    'plugin': ['plugins/menu.py', 'plugins/redirection_first_page.py'],
    'debug': False,
    'level_print': 0,
    'path_config': '',
    'config_directory': '',
    'title_id': True,
    'keywords': {},
    'lib_directory': os.path.dirname(os.path.abspath(__file__)) + '/',
    'use_tidy': False,
    'include_head': [],
}


# ---------------------------------------------------------------------------
# Configuration & CLI
# ---------------------------------------------------------------------------

def parse_arguments():
    parser = argparse.ArgumentParser(description='Generate Website.')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Display more information and keep temporary files.')
    parser.add_argument('-c', '--clean', action='store_true',
                        help='Clean the output directories.')
    parser.add_argument('-i', '--input_config',
                        help='Input yaml configuration file. Default=configure.yaml')
    parser.add_argument('-l', '--light', action='store_true',
                        help='Light mode: only convert .html.j2 files without copying other files.')
    return parser.parse_args()


def load_config(meta, log):
    """Load YAML config file and resolve directory paths."""
    config_file = meta['config_file']
    if not config_file:
        return

    if not os.path.isfile(config_file):
        log.error(f"Cannot find configuration file '{config_file}'")
        sys.exit(1)

    with open(config_file) as fid:
        config = yaml.safe_load(fid) or {}
    if not isinstance(config, dict):
        log.error(f"Invalid configuration file '{config_file}' (expected key: value pairs)")
        sys.exit(1)
    meta.update(config)

    meta['config_directory'] = os.path.dirname(os.path.abspath(config_file)) + '/'

    # Resolve paths relative to config directory
    config_dir = meta['config_directory']
    meta['source_directory'] = config_dir + meta['source_directory']
    meta['site_directory'] = config_dir + meta['site_directory']
    meta['theme'] = config_dir + meta['theme']
    if 'cache_video_directory' in meta:
        meta['cache_video_directory'] = config_dir + meta['cache_video_directory']


def normalize_config(meta):
    """Directories always end with '/' (plugins concatenate paths), and
    'plugin' is always a list."""
    for key in ('source_directory', 'site_directory', 'theme', 'cache_video_directory'):
        if key in meta and meta[key] and not meta[key].endswith('/'):
            meta[key] += '/'
    if isinstance(meta.get('plugin'), str):
        meta['plugin'] = [meta['plugin']]
    elif meta.get('plugin') is None:
        meta['plugin'] = []


# Directories renamed in the v2 layout: old path fragment -> new one
RENAMED_DIRECTORIES = {'theme_templates/': 'themes/', 'src_site_example/': 'example/'}


def validate_directories(meta, log):
    """Check that required directories exist.

    Paths using the directory names of the previous layout
    (theme_templates/, src_site_example/) are redirected to the new ones
    with a warning, so that existing configure.yaml files keep working.
    """
    for key in ('source_directory', 'theme'):
        path = meta[key]
        if os.path.isdir(path):
            continue
        for old, new in RENAMED_DIRECTORIES.items():
            if old in path and os.path.isdir(path.replace(old, new)):
                meta[key] = path.replace(old, new)
                log.warning(f"'{old}' was renamed '{new}': using '{meta[key]}' "
                            f"(update '{key}' in your configuration file)")
                break

    for key, label in [('source_directory', 'Source'), ('theme', 'Theme')]:
        if not os.path.isdir(meta[key]):
            log.error(f"{label} directory not found: '{meta[key]}'")
            sys.exit(1)


# ---------------------------------------------------------------------------
# Plugin system
# ---------------------------------------------------------------------------

# Plugins renamed in the v2 layout
RENAMED_PLUGINS = {'auto-wrap.py': 'auto_wrap.py'}


def resolve_plugin_path(meta, plugin_path, log):
    """Find a plugin file: absolute path, relative to the configuration
    directory, or relative to the generator directory (default plugins).
    Renamed plugins (auto-wrap.py) are redirected with a warning."""
    candidates = [plugin_path]
    for old, new in RENAMED_PLUGINS.items():
        if plugin_path.endswith(old):
            candidates.append(plugin_path[:-len(old)] + new)
    for candidate in candidates:
        for base in ('', meta['config_directory'], meta['lib_directory']):
            if os.path.isabs(candidate) != (base == ''):
                continue
            full_path = base + candidate
            if os.path.isfile(full_path):
                if candidate != plugin_path:
                    log.warning(f"Plugin '{plugin_path}' was renamed: using '{full_path}' "
                                f"(update 'plugin' in your configuration file)")
                return full_path
    return None


def resolve_plugins(meta, log):
    """Resolve the plugin paths once. Returns (full paths found, number missing)."""
    found, missing = [], 0
    for plugin_path in meta['plugin']:
        full_path = resolve_plugin_path(meta, plugin_path, log)
        if full_path is None:
            log.error(f'Plugin not found: {plugin_path}')
            missing += 1
        else:
            found.append(full_path)
    return found, missing


def run_plugins(meta, hook_name, log):
    """Run a plugin hook (pre_process / mid_process / post_process) for the
    plugins in meta['plugin_paths']. Returns the number of plugins that failed."""
    failures = 0
    for full_path in meta['plugin_paths']:
        try:
            spec = importlib.util.spec_from_file_location('plugin', full_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, hook_name):
                log.keyvalue('Run plugin', full_path.split('/')[-1])
                getattr(module, hook_name)(meta)
        except Exception as e:
            log.error(f'Plugin {full_path} failed ({hook_name}): {type(e).__name__}: {e}')
            log.debug(traceback.format_exc())
            failures += 1
    return failures


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def prepare_data(meta, log):
    """Copy sources and theme, find templates, extract metadata."""
    dir_source = meta['source_directory']
    dir_site = meta['site_directory']

    if meta['args'].light:
        log.keyvalue('info', 'Light mode: copying only .html.j2 files', indent_level=1)
        source_files = filesystem.find_files_in_hierarchy(dir_source, lambda f: f.endswith('.html.j2'))
        for element in source_files:
            src_path = element['path'].filepath()
            dst_path = dir_site + '/' + element['path'].filepath_local()
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
    else:
        log.debug(f"Copy source files '{dir_source}' -> '{dir_site}'")
        filesystem.copy_directories(dir_source, dir_site)
        log.debug(f"Copy theme '{meta['theme']}' -> '{dir_site}theme/'")
        filesystem.copy_directories(meta['theme'], dir_site + 'theme/')

    template_files = filesystem.find_files_in_hierarchy(dir_site, lambda f: f.endswith('.html.j2'))
    log.debug(f"Found {len(template_files)} template files in '{dir_site}'")
    generator_tool.extract_additional_config(template_files)
    sitemap = generator_tool.extract_titles(template_files)

    if not meta['args'].light:
        generator_tool.export_sitemap(sitemap, dir_site + '/sitemap/', meta)
        generator_tool.export_structure(template_files, dir_site + '/structure/', dir_site)

    return template_files, sitemap


def discard_page(meta, element):
    """Remove the outputs of a page that failed (kept in debug mode)."""
    if meta['debug']:
        return
    j2_path = element['path'].filepath()
    for path in (j2_path, j2_path.replace('.html.j2', '.html')):
        if os.path.isfile(path):
            os.remove(path)


def render_jinja(meta, template_files, sitemap, log):
    """Render all Jinja2 templates. Returns the list of templates that failed."""
    dir_site = meta['site_directory']
    file_loader = FileSystemLoader(dir_site)
    env = Environment(loader=file_loader, extensions=['jinja_markdown.MarkdownExtension'])

    log.keyvalue('Found', f'{len(template_files)} template files')
    failed = []
    for k, element in enumerate(template_files):
        template_local = element['path'].filepath_local()
        path_to_root = element['path'].path_to_root()

        # Build sitemap keywords
        for id_site in sitemap:
            url = path_to_root + sitemap[id_site]['path'].filepath_local().replace('.html.j2', '.html')
            meta['keywords']['pathTo_' + id_site] = url
            meta['keywords']['linkTo_' + id_site] = f'<a href="{url}">{id_site}</a>'

        log.debug(f'- {template_local}')
        try:
            template = env.get_template(template_local)
            output_html = template.render({**meta['keywords'],
                                           'pathToRoot': path_to_root, 'pageID': k})
        except Exception as e:
            log.error(f'Jinja2 error in {template_local}: {e}')
            failed.append(element)
            # Remove the template and any output of a previous generation
            stale_output = element['path'].filepath().replace('.html.j2', '.html')
            if os.path.isfile(stale_output):
                os.remove(stale_output)
            discard_page(meta, element)
            continue

        output_path = element['path'].filepath().replace('.html.j2', '.html')
        with open(output_path, 'w') as fid:
            fid.write(output_html)

    return failed


def render_lhtml(meta, template_files, log):
    """Run LHTML conversion on all rendered templates, with optional HTML tidy.
    Returns the list of templates that failed."""
    tidy_options = {'doctype': 'html5', 'show-warnings': 'no'}
    python_minor = int(platform.python_version_tuple()[1])
    if python_minor >= 8:
        tidy_options['warn-proprietary-attributes'] = 'no'

    tidylib.BASE_OPTIONS = {}
    failed = []

    for element in template_files:
        html_path = element['path'].filepath().replace('.html.j2', '.html')

        if not os.path.isfile(html_path):
            # Jinja2 rendering failed for this page (error already reported)
            continue
        log.debug(f'- {html_path}')
        with open(html_path, 'r') as fid:
            input_html = fid.read()

        meta['current_directory'] = element['path'].root_directory + element['path'].path_local

        try:
            output_html = lhtml.run(input_html, meta)
        except Exception as e:
            # Enrich error with line number if position is available
            msg = str(e)
            if hasattr(e, 'source_pos') and e.source_pos >= 0:
                line = input_html[:e.source_pos].count('\n') + 1
                msg = f'line {line}: {msg}'
            log.error(f'{html_path}: {msg}')
            failed.append(element)
            discard_page(meta, element)
            continue

        if meta['use_tidy']:
            tidy_html, error = tidylib.tidy_document(output_html, options=tidy_options)
            if error:
                log.error(f'Tidy error in {html_path}:\n{error}')
                if meta['debug']:
                    for k, line in enumerate(output_html.split('\n')):
                        log.display(f'{k + 1}: {line}', debug_level=0)
            output_html = tidy_html

        with open(html_path, 'w') as fid:
            fid.write(output_html)

        if not meta['debug']:
            j2_path = element['path'].filepath()
            if os.path.isfile(j2_path):
                os.remove(j2_path)

    return failed


def compile_sass(meta, log):
    """Find and compile .sass files to .css."""
    dir_site = meta['site_directory']
    sass_files = filesystem.find_files_in_hierarchy(dir_site, lambda f: f.endswith('.sass'))
    if not sass_files:
        return
    try:
        import sass
    except ImportError:
        log.warning(f'{len(sass_files)} .sass file(s) not compiled: '
                    'install libsass (pip install libsass)')
        return
    log.debug(f'Compile {len(sass_files)} sass files')

    for element in sass_files:
        path_sass = element['path'].filepath()
        css_txt = sass.compile(filename=path_sass)

        path_css = path_sass.replace('.sass', '.css')
        with open(path_css, 'w') as fid:
            fid.write(css_txt)

        os.remove(path_sass)


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

def clean_directories(meta):
    site_dir = meta['site_directory']
    if os.path.isdir(site_dir):
        shutil.rmtree(site_dir)
    for d in ['lib/__pycache__', 'plugins/__pycache__']:
        if os.path.isdir(d):
            shutil.rmtree(d)
    print('Directories cleaned\n')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    meta = copy.deepcopy(META_DEFAULTS)
    args = parse_arguments()

    if args.input_config is not None:
        meta['config_file'] = args.input_config
    if args.debug:
        meta['debug'] = True
    meta['args'] = args

    log = logger.Logger(indent_level_base=meta['level_print'], debug_level=2 if args.debug else 1)
    meta['log'] = log

    load_config(meta, log)
    normalize_config(meta)
    validate_directories(meta, log)

    if args.clean:
        clean_directories(meta)
        return

    log.display('[bold white]****************************', pre='\n')
    log.display('[bold white]  Start website generator')
    log.display('[bold white]****************************')
    log.keyvalue('info', f"Source: {meta['source_directory']}", indent_level=1)
    log.keyvalue('info', f"Plugins: {meta['plugin']}", indent_level=1)
    meta['plugin_paths'], plugin_failures = resolve_plugins(meta, log)

    # Data preparation
    log.title('Data preparation', pre='\n')
    log.tic()
    template_files, sitemap = prepare_data(meta, log)
    log.ok_elapsed()

    # Pre-process plugins
    log.title('Pre-process', pre='\n')
    log.tic()
    plugin_failures += run_plugins(meta, 'pre_process', log)
    log.ok_elapsed()

    # Jinja2 rendering
    log.title('Convert HTML', pre='\n')
    log.tic()
    failed = render_jinja(meta, template_files, sitemap, log)
    if failed:
        log.error(f'{len(failed)} page(s) not generated because of Jinja2 errors')

    # Mid-process plugins
    log.title('Mid-process', pre='\n')
    log.tic()
    plugin_failures += run_plugins(meta, 'mid_process', log)
    log.ok_elapsed()

    # LHTML conversion
    failed += render_lhtml(meta, template_files, log)
    log.ok_elapsed()

    # SASS compilation
    if not args.light:
        compile_sass(meta, log)

    # Post-process plugins
    log.title('Post-process', pre='\n')
    log.tic()
    plugin_failures += run_plugins(meta, 'post_process', log)
    log.ok_elapsed()

    print()
    if failed:
        log.error(f'{len(failed)} page(s) failed (see errors above)')
    if plugin_failures:
        log.error(f'{plugin_failures} plugin error(s) (see errors above, use -d for details)')
    if failed or plugin_failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
