"""Static website generator built on LHTML.

Pipeline: copy sources → Jinja2 rendering → LHTML conversion → SASS compilation
with plugin hooks at pre/mid/post stages.
"""

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, TemplateError
from jinja2 import meta as jinja_meta
import tidylib
import yaml
import json
import os
import shutil
import argparse
import sys
import importlib.util
import traceback

from lib import deck
from lib import design
from lib import filesystem
from lib import generator_tool
from lib import lint
from lib import logger
from lib import pages
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
    parser.add_argument('--only', metavar='POINTER', action='append',
                        help='Generate only these pages (deck pointer: directory, file, glob; repeatable) '
                             'in the existing site; a full build when the pages of the site changed.')
    parser.add_argument('--lint', action='store_true',
                        help='List the values written by hand in the pages (positions, spacers, font sizes) '
                             'with the layout or macro of the design that replaces them; no generation.')
    parser.add_argument('--check-config', action='store_true',
                        help='Validate and display resolved configuration without generating files.')
    parser.add_argument('--layout', action='store_true',
                        help='Write a layout report (block positions, collisions, overflows) '
                             'of each page in .layout/ (plugin layout_report.py, requires npm install).')
    parser.add_argument('--deck', metavar='FILE',
                        help='Deck file (order of the slides) replacing the deck of the configuration.')
    parser.add_argument('--scaffold', action='store_true',
                        help='Create the source of the deck slides that do not exist yet (slides with a title).')
    parser.add_argument('--serve', action='store_true', help='Serve the generated site on localhost.')
    parser.add_argument('--watch', action='store_true', help='Rebuild when sources, theme or configuration change.')
    parser.add_argument('--port', type=int, default=8000, help='Local HTTP port (default: 8000).')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    if (args.serve or args.watch) and (args.clean or args.check_config):
        parser.error('--serve/--watch cannot be combined with --clean or --check-config')
    if args.only and (args.clean or args.check_config):
        parser.error('--only cannot be combined with --clean or --check-config')
    if args.lint and (args.clean or args.check_config or args.serve or args.watch):
        parser.error('--lint cannot be combined with --clean, --check-config, --serve or --watch')
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

def load_deck(meta):
    """The deck (meta['deck']: --deck, else the 'deck' of the configuration), or None."""
    if meta.get('deck') is None:
        return None
    loaded = deck.load_deck(meta['deck'], meta['config_directory'])
    deck.check_sources(loaded, meta['source_directory'], meta.get('published_site_directory')
                       or meta['site_directory'])
    return loaded


def select_pages(meta, log, scaffold=False):
    """Pages to generate, in order, with their names in the site: the pages of
    the project in file order, or the pages of the deck (from the project and
    other projects). With `scaffold`, the planned slides of the deck are
    created first."""
    loaded_deck = load_deck(meta)
    site = [meta['site_directory']]
    found = pages.discover(pages.Source(None, meta['source_directory']), exclude=site)
    if loaded_deck is None:
        pages.name_outputs(found)
        return found
    for name, root in loaded_deck.sources.items():
        if any(e.source == name for e in loaded_deck.entries):
            found += pages.discover(pages.Source(name, root), exclude=site)
    result = deck.apply_deck(loaded_deck, found)
    if scaffold and result.missing:
        for path in deck.scaffold(result.missing, meta['source_directory']):
            log.keyvalue('info', f'Deck: created {os.path.relpath(path)}', indent_level=1)
        return select_pages(meta, log)
    for warning in result.warnings:
        log.warning(f'Deck: {warning}')
    if not result.pages:
        log.warning('Deck: no page selected (the site will be empty)')
    for entry in result.missing:
        log.warning(f"Deck: '{entry.pointer}' ({entry.meta['title']}) has no source yet "
                    f"(--scaffold creates it)")
    log.keyvalue('info', f'Deck: {result.summary()}', indent_level=1)
    if result.unlisted:
        names = ', '.join(p.label for p in result.unlisted[:5])
        more = f' and {len(result.unlisted) - 5} more' if len(result.unlisted) > 5 else ''
        log.keyvalue('info', f'Deck: {len(result.unlisted)} page(s) not in the deck, not generated: '
                             f'{names}{more}', indent_level=1)
    pages.name_outputs(result.pages)
    return result.pages


def only_pages(meta, selected, log):
    """--only: the pages it names, or None for a full build (no previous site,
    or its pages are not those of this build: a deck or a page changed)."""
    sources = {p.source.name: p.source.root for p in selected if p.source.name}
    built = deck.named_pages(selected, meta['args'].only, sources)
    previous = os.path.join(meta['site_directory'], 'structure/structure.json')
    if not os.path.isfile(previous):
        log.keyvalue('info', '--only: no previous build, full build', indent_level=1)
        return None
    with open(previous, encoding='utf-8') as fid:
        names = [entry['dir'] + entry['filename'] for entry in json.load(fid)]
    if names != [page.site_html for page in selected]:
        log.keyvalue('info', '--only: the pages of the site changed, full build', indent_level=1)
        return None
    log.keyvalue('info', f"--only: {', '.join(p.label for p in built)}", indent_level=1)
    return built


def prepare_data(meta, selected, built, log):
    """Copy the pages to generate with the sources and theme into the site
    (only their templates and assets for --only), extract the titles of all
    the pages and export the structure. Returns the sitemap."""
    dir_source = meta['source_directory']
    dir_site = meta['site_directory']
    only = meta['only']

    warnings = []
    if not only:
        log.debug(f"Copy source files '{dir_source}' -> '{dir_site}'")
        warnings += filesystem.copy_directories(dir_source, dir_site, skip=pages.is_template,
                                                exclude=[meta.get('published_site_directory')])
        log.debug(f"Copy theme '{meta['theme']}' -> '{dir_site}theme/'")
        warnings += filesystem.copy_directories(meta['theme'], dir_site + 'theme/')
    if only:        # a page that fails keeps its previous version
        meta['previous_pages'] = {}
        for page in built:
            if os.path.isfile(dir_site + page.site_html):
                with open(dir_site + page.site_html, 'rb') as fid:
                    meta['previous_pages'][page.site_html] = fid.read()
    warnings += pages.place(built, dir_site, project_assets=only)
    for warning in warnings:
        log.warning(warning)

    log.debug(f"Found {len(selected)} template files")
    sitemap = generator_tool.extract_titles(selected)
    generator_tool.export_sitemap(sitemap, dir_site + 'sitemap/')
    meta['structure'] = generator_tool.export_structure(selected, dir_site + 'structure/')
    built_ids = {id(page) for page in built}
    meta['built'] = [entry for page, entry in zip(selected, meta['structure']) if id(page) in built_ids]
    return sitemap


def discard_page(meta, page):
    """Remove the outputs of a page that failed (the template is kept in debug
    mode); with --only, its previous version is restored."""
    paths = [page.site_html] + ([] if meta['debug'] else [page.site_template])
    for path in paths:
        full_path = meta['site_directory'] + path
        if os.path.isfile(full_path):
            os.remove(full_path)
    previous = meta.get('previous_pages', {}).get(page.site_html)
    if previous is not None:
        with open(meta['site_directory'] + page.site_html, 'wb') as fid:
            fid.write(previous)


def sitemap_keywords_used(env, templates):
    """Names pathTo_<id> / linkTo_<id> used by the templates and by the
    templates they extend, include or import (only these are computed for
    each page); None when a template is chosen at run time (all are used)."""
    used, seen, pending = set(), set(), list(templates)
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            source = env.loader.get_source(env, name)[0]
            ast = env.parse(source)
        except TemplateError:
            continue                    # reported when the page is rendered
        used.update(n for n in jinja_meta.find_undeclared_variables(ast)
                    if n.startswith(('pathTo_', 'linkTo_')))
        for reference in jinja_meta.find_referenced_templates(ast):
            if reference is None:
                return None
            pending.append(reference)
    return used


def jinja_environment(meta, selected, built):
    """Jinja environment: the templates of the pages to generate (as the
    plugins left them in the site), then the files of the sources (includes,
    imports: the project first, then the other projects), then the site (theme)."""
    dir_site = meta['site_directory']
    templates = {}
    for page in built:
        with open(dir_site + page.site_template, encoding='utf-8') as fid:
            templates[page.site_template] = fid.read()
    roots = [meta['source_directory']] + sorted({p.source.root for p in selected if p.source.name})
    loader = ChoiceLoader([DictLoader(templates)] + [FileSystemLoader(root) for root in roots]
                         + [FileSystemLoader(dir_site)])
    return Environment(loader=loader, extensions=['jinja_markdown.MarkdownExtension'])


def render_jinja(meta, selected, built, sitemap, log):
    """Render the Jinja2 templates of the pages to generate (`built`, among the
    pages of the site `selected`). Returns the list of pages that failed."""
    dir_site = meta['site_directory']
    env = jinja_environment(meta, selected, built)
    used = sitemap_keywords_used(env, [page.site_template for page in built])
    targets = {id_site: page.site_html for id_site, page in sitemap.items()
               if used is None or 'pathTo_' + id_site in used or 'linkTo_' + id_site in used}

    log.keyvalue('Found', f'{len(built)} template files')
    failed = []
    built_ids = {id(page) for page in built}
    entries = {id(page): entry for page, entry in zip(selected, meta['structure'])}
    for k, page in enumerate(selected):
        if id(page) not in built_ids:
            continue
        links = {}
        for id_site, target in targets.items():
            url = page.path_to_root + target
            links['pathTo_' + id_site] = url
            links['linkTo_' + id_site] = f'<a href="{url}">{id_site}</a>'

        log.debug(f'- {page.site_template}')
        try:
            template = env.get_template(page.site_template)
            output_html = template.render({**meta['keywords'], **links, 'params': page.params,
                                           'page': entries[id(page)],
                                           'pathToRoot': page.path_to_root, 'pageID': k})
        except Exception as e:
            log.error(f'Jinja2 error in {page.site_template}: {e}')
            failed.append(page)
            discard_page(meta, page)
            continue

        filesystem.write_file(dir_site + page.site_html, output_html)

    return failed


def prepare_design(meta, log):
    """Load the design (theme design.yaml + 'design' of the configuration),
    write theme/css/design.css and structure/design.md, give the macros to LHTML."""
    meta['design'] = design.load_design(meta['theme'], meta.get('design'), meta['config_directory'])
    meta['macros'] = design.lhtml_macros(meta['design'])
    # Always written (even empty): the theme may link it, and --only must not
    # keep the design.css of a previous design.
    path = design.write_design(meta, meta['design'])
    log.debug(f"Design: {len(meta['macros'])} macro(s), {path}")


def render_lhtml(meta, selected, log):
    """Run LHTML conversion on all rendered templates, with optional HTML tidy.
    Returns the list of pages that failed."""
    tidy_options = {'doctype': 'html5', 'show-warnings': 'no', 'warn-proprietary-attributes': 'no'}

    tidylib.BASE_OPTIONS = {}
    failed = []

    for page in selected:
        html_path = meta['site_directory'] + page.site_html

        if not os.path.isfile(html_path):
            # Jinja2 rendering failed for this page (error already reported)
            continue
        log.debug(f'- {html_path}')
        with open(html_path, 'r') as fid:
            input_html = fid.read()

        meta['current_directory'] = meta['site_directory'] + page.site_directory

        try:
            output_html = lhtml.run(input_html, meta)
        except Exception as e:
            # Enrich error with line number if position is available
            msg = str(e)
            if hasattr(e, 'source_pos') and e.source_pos >= 0:
                line = input_html[:e.source_pos].count('\n') + 1
                msg = f'line {line}: {msg}'
            log.error(f'{html_path}: {msg}')
            failed.append(page)
            discard_page(meta, page)
            continue

        if meta['use_tidy']:
            tidy_html, error = tidylib.tidy_document(output_html, options=tidy_options)
            if error:
                log.error(f'Tidy error in {html_path}:\n{error}')
                if meta['debug']:
                    for k, line in enumerate(output_html.split('\n')):
                        log.display(f'{k + 1}: {line}', debug_level=0)
            output_html = tidy_html

        filesystem.write_file(html_path, output_html)

        if not meta['debug']:
            j2_path = meta['site_directory'] + page.site_template
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

        path_css = path_sass[:-len('.sass')] + '.css'
        filesystem.write_file(path_css, css_txt)

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
    meta['deck'] = deck.deck_source(args.deck, config.deck, config_file.parent)
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
        # The deck and the design are read (not the pages): errors before any build
        try:
            loaded_deck = load_deck(meta)
            loaded_design = design.load_design(meta['theme'], meta.get('design'), meta['config_directory'])
        except (deck.DeckError, design.DesignError) as exc:
            log.error(str(exc))
            sys.exit(1)
        print(yaml.safe_dump({
            'config_file': str(config_file),
            'source_directory': config.source_directory,
            'site_directory': config.site_directory,
            'theme': config.theme,
            'deck': meta['deck'] if loaded_deck is None else {
                'file': meta['deck'] if isinstance(meta['deck'], str) else '(inline)',
                'slides': len(loaded_deck.entries), 'sources': loaded_deck.sources},
            'design': {'tokens': len(design.flatten_tokens(loaded_design['tokens'])),
                       'macros': sorted(loaded_design['macros'])},
            'plugin_paths': context.plugin_paths,
            'debug': config.debug,
            'level_print': config.level_print,
            'use_tidy': config.use_tidy,
        }, sort_keys=False))
        return
    if args.clean:
        clean_directories(meta)
        return
    if args.lint:
        try:
            selected = select_pages(meta, log)
            if args.only:
                sources = {p.source.name: p.source.root for p in selected if p.source.name}
                selected = deck.named_pages(selected, args.only, sources)
            loaded_design = design.load_design(meta['theme'], meta.get('design'), meta['config_directory'])
        except (deck.DeckError, design.DesignError, ValueError) as exc:
            log.error(str(exc))
            sys.exit(1)
        lint_pages(selected, loaded_design, log, details=True)
        return

    built = None
    try:
        selected = select_pages(meta, log, scaffold=args.scaffold)
        built = only_pages(meta, selected, log) if args.only else None
        meta['only'] = built is not None
        if meta['only']:
            # In the site itself: copying it into a staging directory would
            # cost more than the pages generated
            generate_site(meta, selected, built)
        else:
            with staged_site(meta):
                generate_site(meta, selected, selected)
    except Exception as exc:
        log.error(f"Build failed{'' if built is not None else '; previous site preserved'}: {exc}")
        log.debug(traceback.format_exc())
        raise SystemExit(1)


def lint_pages(selected, loaded_design, log, details=False):
    """Design lint of the pages (lib/lint.py): the summary, and with `details`
    each finding (path:line). Returns the number of findings."""
    linter = lint.Linter(loaded_design)
    total, pages_with, seen = 0, 0, set()
    for page in selected:
        if page.src in seen:            # occurrences of a page: once
            continue
        seen.add(page.src)
        findings = linter.lint_file(page.src, {**page.config, **page.meta}.get('layout'))
        total += len(findings)
        pages_with += bool(findings)
        if details:
            path = os.path.relpath(page.src)
            for f in findings:
                print(f'{path}:{f.line}: {f.kind}: {f.text}\n    -> {f.advice}')
    summary = (f'{total} value(s) written by hand in {pages_with} of {len(seen)} page(s)' if total
               else f'no value written by hand in {len(seen)} page(s)')
    if details:
        print(f'\nLint: {summary}')
    elif total:
        log.keyvalue('info', f'Lint: {summary} (python generate.py --lint)', indent_level=1)
    return total


def generate_site(meta, selected, built):
    """Generate the pages `built` among the pages of the site `selected` (all
    of them, except with --only)."""
    log = meta['log']
    plugin_failures = 0
    log.display('[bold white]****************************', pre='\n')
    log.display('[bold white]  Start website generator')
    log.display('[bold white]****************************')
    log.keyvalue('info', f"Source: {meta['source_directory']}", indent_level=1)
    log.keyvalue('info', f"Plugins: {meta['plugin']}", indent_level=1)

    # Data preparation
    log.title('Data preparation', pre='\n')
    log.tic()
    sitemap = prepare_data(meta, selected, built, log)
    prepare_design(meta, log)
    lint_pages(built, meta['design'], log)
    log.ok_elapsed()

    # Pre-process plugins
    log.title('Pre-process', pre='\n')
    log.tic()
    plugin_failures += run_plugins(meta, 'pre_process', log)
    log.ok_elapsed()

    # Jinja2 rendering
    log.title('Convert HTML', pre='\n')
    log.tic()
    failed = render_jinja(meta, selected, built, sitemap, log)
    if failed:
        log.error(f'{len(failed)} page(s) not generated because of Jinja2 errors')

    # Mid-process plugins
    log.title('Mid-process', pre='\n')
    log.tic()
    plugin_failures += run_plugins(meta, 'mid_process', log)
    log.ok_elapsed()

    # LHTML conversion
    failed += render_lhtml(meta, built, log)
    log.ok_elapsed()

    # SASS compilation
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
    if not hasattr(lhtml, 'registry_with_macros'):
        sys.exit('static_website_lhtml requires lhtml-markup >= 2.5 (pip install -U lhtml-markup)')
    args = parse_arguments()
    if args.serve or args.watch:
        from lib.development import develop
        develop(args, build_once)
    else:
        build_once(args)


if __name__ == '__main__':
    main()
