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
import traceback

from lib import filesystem
from lib import generator_tool
from lib import logger
from lib.configuration import BuildContext, ConfigError, load_config, validate_paths, layout_output_directory
from lib.build_output import staged_site

import lhtml


# Configuration & CLI

def parse_arguments():
    parser = argparse.ArgumentParser(description='Generate Website.')
    debug_group = parser.add_mutually_exclusive_group()
    debug_group.add_argument('-d', '--debug', action='store_true', default=None,
                        help='Display more information and keep temporary files.')
    debug_group.add_argument('--no-debug', dest='debug', action='store_false',
                             help='Disable debug mode configured in YAML.')
    parser.add_argument('-c', '--clean', action='store_true',
                        help='Clean the output directories.')
    parser.add_argument('-i', '--input_config',
                        help='Input yaml configuration file. Default=configure.yaml')
    parser.add_argument('-l', '--light', action='store_true',
                        help='Light mode: only convert .html.j2 files without copying other files.')
    parser.add_argument('--check-config', action='store_true',
                        help='Validate and display resolved configuration without generating files.')
    parser.add_argument('--layout', action='store_true',
                        help='Write a layout report (block positions, collisions, overflows) '
                             'of each page in .layout/ (plugin layout_report.py, requires npm install).')
    parser.add_argument('--serve', action='store_true', help='Serve the generated site on localhost.')
    parser.add_argument('--watch', action='store_true', help='Rebuild when sources, theme or configuration change.')
    parser.add_argument('--port', type=int, default=8000, help='Local HTTP port (default: 8000).')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    if (args.serve or args.watch) and (args.clean or args.check_config):
        parser.error('--serve/--watch cannot be combined with --clean or --check-config')
    if args.watch and args.light:
        parser.error('--watch performs full rebuilds; omit --light')
    return args



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


LAYOUT_PLUGIN = 'plugins/layout_report.py'


def add_layout_plugin(meta):
    """Add the layout report plugin (--layout): after the other plugins, but
    before generate_pdf, which removes the site directory."""
    plugins = [p for p in meta['plugin'] if not p.endswith('layout_report.py')]
    position = next((k for k, p in enumerate(plugins) if p.endswith('generate_pdf.py')), len(plugins))
    plugins.insert(position, meta['lib_directory'] + LAYOUT_PLUGIN)
    meta['plugin'] = plugins


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
        structure_path = os.path.join(dir_site, 'structure/structure.yaml')
        current_pages = {e['path'].filepath_local().replace('.html.j2', '.html')
                         for e in source_files}
        if os.path.isfile(structure_path):
            with open(structure_path) as fid:
                previous_pages = yaml.safe_load(fid) or []
            for entry in previous_pages:
                relative = entry['dir'] + entry['filename']
                if relative not in current_pages:
                    for suffix in ('', '.j2'):
                        stale = os.path.join(dir_site, relative + suffix)
                        if os.path.isfile(stale):
                            os.remove(stale)
        generator_tool.extract_additional_config(source_files)
        for element in source_files:
            src_path = element['path'].filepath()
            dst_path = dir_site + '/' + element['path'].filepath_local()
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            element['path'].root_directory = dir_site
    else:
        log.debug(f"Copy source files '{dir_source}' -> '{dir_site}'")
        filesystem.copy_directories(dir_source, dir_site)
        log.debug(f"Copy theme '{meta['theme']}' -> '{dir_site}theme/'")
        filesystem.copy_directories(meta['theme'], dir_site + 'theme/')

    template_files = (source_files if meta['args'].light else
                      filesystem.find_files_in_hierarchy(dir_site, lambda f: f.endswith('.html.j2')))
    log.debug(f"Found {len(template_files)} template files in '{dir_site}'")
    if not meta['args'].light:
        generator_tool.extract_additional_config(template_files)
    sitemap = generator_tool.extract_titles(template_files)

    sitemap_dir = os.path.join(dir_site, 'sitemap')
    if meta['args'].light and os.path.isdir(sitemap_dir):
        shutil.rmtree(sitemap_dir)
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
    print('Directories cleaned\n')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_once(args):
    try:
        config, config_file, warnings = load_config(
            args.input_config or 'configure.yaml', debug_override=args.debug)
        validate_paths(config, config_file, require_inputs=not args.clean or args.check_config)
    except ConfigError as exc:
        logger.Logger().error(str(exc))
        sys.exit(1)

    log = logger.Logger(indent_level_base=config.level_print,
                        debug_level=2 if config.debug else 1)
    for warning in warnings:
        log.warning(warning)
    context = BuildContext(config, config_file, args, log)
    meta = context.meta
    if args.layout:
        add_layout_plugin(meta)


    # Diagnostic mode takes precedence over --clean and never runs plugins.
    if args.check_config or not args.clean:
        paths, plugin_failures = resolve_plugins(meta, log)
        context.plugin_paths.extend(paths)
        if plugin_failures:
            sys.exit(1)
    if any(path.endswith('layout_report.py') for path in context.plugin_paths):
        try:
            layout_output_directory(meta)
        except ConfigError as exc:
            log.error(str(exc))
            sys.exit(1)
    if args.check_config:
        print(yaml.safe_dump({
            'config_file': str(config_file),
            'source_directory': config.source_directory,
            'site_directory': config.site_directory,
            'theme': config.theme,
            'plugin_paths': context.plugin_paths,
            'debug': config.debug,
            'level_print': config.level_print,
            'use_tidy': config.use_tidy,
        }, sort_keys=False))
        return
    if args.clean:
        clean_directories(meta)
        return

    try:
        with staged_site(meta):
            generate_site(meta)
    except Exception as exc:
        log.error(f'Build failed; previous site preserved: {exc}')
        log.debug(traceback.format_exc())
        raise SystemExit(1)


def generate_site(meta):
    args, log = meta['args'], meta['log']
    plugin_failures = 0
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
    if not failed and not plugin_failures:
        plugin_failures += run_plugins(meta, 'post_process', log)
    log.ok_elapsed()

    print()
    if failed:
        log.error(f'{len(failed)} page(s) failed (see errors above)')
    if plugin_failures:
        log.error(f'{plugin_failures} plugin error(s) (see errors above, use -d for details)')
    if failed or plugin_failures:
        raise RuntimeError('Page or plugin errors (see above)')


def main():
    args = parse_arguments()
    if args.serve or args.watch:
        from lib.development import develop
        develop(args, build_once)
    else:
        build_once(args)


if __name__ == '__main__':
    main()
