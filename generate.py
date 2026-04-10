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
        config = yaml.safe_load(fid)
    meta.update(config)

    meta['config_directory'] = os.path.dirname(os.path.abspath(config_file)) + '/'

    # Resolve paths relative to config directory
    config_dir = meta['config_directory']
    meta['source_directory'] = config_dir + meta['source_directory']
    meta['site_directory'] = config_dir + meta['site_directory']
    meta['theme'] = config_dir + meta['theme']
    if 'cache_video_directory' in meta:
        meta['cache_video_directory'] = config_dir + meta['cache_video_directory']


def validate_directories(meta, log):
    """Check that required directories exist."""
    for key, label in [('source_directory', 'Source'), ('theme', 'Theme')]:
        if not os.path.isdir(meta[key]):
            log.error(f"{label} directory not found: '{meta[key]}'")
            sys.exit(1)


# ---------------------------------------------------------------------------
# Plugin system
# ---------------------------------------------------------------------------

def run_plugins(meta, hook_name, log):
    """Run a plugin hook (pre_process / mid_process / post_process)."""
    for plugin_path in meta['plugin']:
        full_path = meta['config_directory'] + plugin_path
        if not os.path.isfile(full_path):
            log.error(f'Plugin not found: {full_path}')
            continue

        try:
            spec = importlib.util.spec_from_file_location('plugin', full_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, hook_name):
                log.keyvalue('Run plugin', full_path.split('/')[-1])
                getattr(module, hook_name)(meta)
        except Exception as e:
            log.error(f'Plugin {full_path} failed: {e}')


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
        filesystem.copy_directories(dir_source, dir_site)
        filesystem.copy_directories(meta['theme'], dir_site + '/theme/')

    template_files = filesystem.find_files_in_hierarchy(dir_site, lambda f: f.endswith('.html.j2'))
    generator_tool.extract_additional_config(template_files)
    sitemap = generator_tool.extract_titles(template_files)

    if not meta['args'].light:
        generator_tool.export_sitemap(sitemap, dir_site + '/sitemap/', meta)
        generator_tool.export_structure(template_files, dir_site + '/structure/', dir_site)

    return template_files, sitemap


def render_jinja(meta, template_files, sitemap, log):
    """Render all Jinja2 templates."""
    dir_site = meta['site_directory']
    file_loader = FileSystemLoader(dir_site)
    env = Environment(loader=file_loader, extensions=['jinja_markdown.MarkdownExtension'])

    log.keyvalue('Found', f'{len(template_files)} template files')
    for k, element in enumerate(template_files):
        template_local = element['path'].filepath_local()
        path_to_root = element['path'].path_to_root()

        # Build sitemap keywords
        for id_site in sitemap:
            url = path_to_root + sitemap[id_site]['path'].filepath_local().replace('.html.j2', '.html')
            meta['keywords']['pathTo_' + id_site] = url
            meta['keywords']['linkTo_' + id_site] = f'<a href="{url}">{id_site}</a>'

        try:
            template = env.get_template(template_local)
            output_html = template.render(**meta['keywords'], pathToRoot=path_to_root, pageID=k)
        except Exception as e:
            log.error(f'Jinja2 error in {template_local}: {e}')
            continue

        output_path = element['path'].filepath().replace('.html.j2', '.html')
        with open(output_path, 'w') as fid:
            fid.write(output_html)


def render_lhtml(meta, template_files, log):
    """Run LHTML conversion on all rendered templates, with optional HTML tidy."""
    tidy_options = {'doctype': 'html5', 'show-warnings': 'no'}
    python_minor = int(platform.python_version_tuple()[1])
    if python_minor >= 8:
        tidy_options['warn-proprietary-attributes'] = 'no'

    tidylib.BASE_OPTIONS = {}

    for element in template_files:
        html_path = element['path'].filepath().replace('.html.j2', '.html')

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
            continue

        if meta['use_tidy']:
            tidy_html, error = tidylib.tidy_document(output_html, options=tidy_options)
            if error:
                log.error(f'Tidy error in {html_path}:\n{error}')
            output_html = tidy_html

        with open(html_path, 'w') as fid:
            fid.write(output_html)

        if not meta['debug']:
            j2_path = html_path.replace('.html', '.html.j2')
            if os.path.isfile(j2_path):
                os.remove(j2_path)


def compile_sass(meta, log):
    """Find and compile .sass files to .css."""
    try:
        import sass
    except ImportError:
        return

    dir_site = meta['site_directory']
    sass_files = filesystem.find_files_in_hierarchy(dir_site, lambda f: f.endswith('.sass'))

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
    meta = dict(META_DEFAULTS)
    args = parse_arguments()

    if args.input_config is not None:
        meta['config_file'] = args.input_config
    if args.debug:
        meta['debug'] = True
    meta['args'] = args

    log = logger.Logger(indent_level_base=meta['level_print'])
    meta['log'] = log

    load_config(meta, log)
    validate_directories(meta, log)

    if args.clean:
        clean_directories(meta)
        return

    log.display('[bold white]****************************', pre='\n')
    log.display('[bold white]  Start website generator')
    log.display('[bold white]****************************')
    log.keyvalue('info', f"Source: {meta['source_directory']}", indent_level=1)
    log.keyvalue('info', f"Plugins: {meta['plugin']}", indent_level=1)

    # Data preparation
    log.title('Data preparation', pre='\n')
    log.tic()
    template_files, sitemap = prepare_data(meta, log)
    log.ok_elapsed()

    # Pre-process plugins
    log.title('Pre-process', pre='\n')
    log.tic()
    run_plugins(meta, 'pre_process', log)
    log.ok_elapsed()

    # Jinja2 rendering
    log.title('Convert HTML', pre='\n')
    log.tic()
    render_jinja(meta, template_files, sitemap, log)

    # Mid-process plugins
    log.title('Mid-process', pre='\n')
    log.tic()
    run_plugins(meta, 'mid_process', log)
    log.ok_elapsed()

    # LHTML conversion
    render_lhtml(meta, template_files, log)
    log.ok_elapsed()

    # SASS compilation
    if not args.light:
        compile_sass(meta, log)

    # Post-process plugins
    log.title('Post-process', pre='\n')
    log.tic()
    run_plugins(meta, 'post_process', log)
    log.ok_elapsed()

    print()


if __name__ == '__main__':
    main()
