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
import tempfile
import argparse
from contextlib import contextmanager
import sys
import importlib.util
import traceback
import warnings as python_warnings

from lib import deck
from lib import credits
from lib import design
from lib import feedback
from lib import figures
from lib import filesystem
from lib import front_matter
from lib import generator_tool
from lib import lint
from lib import dependencies
from lib import source_map
from lib.tracking import TrackingLoader
from lib import source_scan
from lib import theme
from lib import menu
from lib import headings
from lib import wrap
from lib import index_page
from lib import video_cache
from lib.layout import build as layout_build
from lib import logger
from lib import pages
from lib.configuration import BuildContext, ConfigError, load_config, validate_paths
from lib import layout_options
from lib.build_output import staged_site
from lib.structure import documents_directory

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
                             'of each page in .layout/ (lib/layout/, requires npm install).')
    parser.add_argument('--render', metavar='FILE', action='append',
                        help='Render a file as PNG as the slides draw it (an SVG or image at its size, an HTML '
                             'page at the size of the slide), in <layout output>/render/; no build (repeatable).')
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
    if args.render and (args.clean or args.check_config or args.serve or args.watch or args.lint or args.only
                        or args.layout or args.deck or args.scaffold):
        parser.error('--render is used alone (no build)')
    return args



# ---------------------------------------------------------------------------
# Plugin system
# ---------------------------------------------------------------------------

def resolve_plugin_path(meta, plugin_path):
    """Find a plugin file: an absolute path, or a path relative to the
    configuration directory, then to the generator (its own plugins/)."""
    if os.path.isabs(plugin_path):
        return plugin_path if os.path.isfile(plugin_path) else None
    for base in (meta['config_directory'], meta['lib_directory']):
        if (base / plugin_path).is_file():
            return (base / plugin_path).as_posix()
    return None


def resolve_plugins(meta, log):
    """Resolve the plugin paths once. Returns (full paths found, number missing)."""
    found, missing = [], 0
    for plugin_path in meta['plugin']:
        full_path = resolve_plugin_path(meta, plugin_path)
        if full_path is None:
            log.error(f'Plugin not found: {plugin_path}')
            missing += 1
        else:
            found.append(full_path)
    return found, missing


_plugin_modules = {}     # {path: module} of the build (emptied by generate_site)


def load_plugin(full_path):
    """The module of a plugin: loaded once per build, so that it keeps its
    state from a hook to the next (pre_process, mid_process, post_process),
    but not from a build to the next (--watch)."""
    if full_path not in _plugin_modules:
        spec = importlib.util.spec_from_file_location('plugin', full_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _plugin_modules[full_path] = module
    return _plugin_modules[full_path]


def run_plugins(meta, hook_name, log):
    """Run a plugin hook (pre_process / mid_process / post_process) for the
    plugins in meta['plugin_paths']. Returns the number of plugins that failed."""
    failures = 0
    for full_path in meta['plugin_paths']:
        try:
            module = load_plugin(full_path)
            if hasattr(module, hook_name):
                log.keyvalue('Run plugin', full_path.split('/')[-1])
                getattr(module, hook_name)(meta)
        except ConfigError as e:        # what it was asked to do, not what happened
            log.error(f'{e} (configuration of {os.path.basename(full_path)})')
            log.debug(traceback.format_exc())
            failures += 1
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
    # Without a deck, every page of the project is published: a hidden page
    # is a draft and stays out. A deck publishes what it names, so a hidden
    # page it names is published - that is its author asking for it.
    found = pages.discover(pages.Source(None, meta['source_directory']), exclude=site,
                           include_hidden=loaded_deck is not None)
    if loaded_deck is None:
        pages.name_outputs(found)
        return found
    for name, root in loaded_deck.sources.items():
        if any(e.source == name for e in loaded_deck.entries):
            found += pages.discover(pages.Source(name, root), exclude=site, include_hidden=True)
    result = deck.apply_deck(loaded_deck, found)
    if scaffold and result.missing:
        for path in deck.scaffold(result.missing, meta['source_directory']):
            log.keyvalue('info', f'Deck: created {filesystem.shown(path)}', indent_level=1)
        return select_pages(meta, log)
    for warning in result.warnings:
        log.warning(f'Deck: {warning}')
    if not result.pages:
        log.warning('Deck: no page selected (the site will be empty)')
    for entry in result.missing:
        log.warning(f"Deck: '{entry.pointer}' ({entry.meta['title']}) has no source yet "
                    f"(--scaffold creates it)")
    log.keyvalue('info', f'Deck: {result.summary(loaded_deck.duration)}', indent_level=1)
    if (extra := result.over_time(loaded_deck.duration)) is not None:
        log.warning(f'Deck: {extra:g} min over the length of the talk ({loaded_deck.duration:g} min, '
                    f"key 'duration' of the deck)")
    if result.unlisted:
        names = ', '.join(p.label for p in result.unlisted[:5])
        more = f' and {len(result.unlisted) - 5} more' if len(result.unlisted) > 5 else ''
        log.keyvalue('info', f'Deck: {len(result.unlisted)} page(s) not in the deck, not generated: '
                             f'{names}{more}', indent_level=1)
    meta['planned_slides'] = result.missing
    pages.name_outputs(result.pages)
    return result.pages


def other_sources(selected):
    """{name: root} of the other projects of the pages."""
    return {p.source.name: p.source.root for p in selected if p.source.name}


# Guide of the procedure for AI agents, copied into each project (.structure/agents.md)
AGENTS_GUIDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs', 'agents.md')


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
        # The site, and the files of the project that are not content: a link
        # inside the sources would otherwise publish the configuration, the
        # deck (which holds the notes of the author) or the documents written
        # next to them.
        warnings += filesystem.copy_directories(
            dir_source, dir_site, skip=pages.is_build_input,
            exclude=[meta.get('published_site_directory'), meta.get('config_file'),
                     meta['deck'] if isinstance(meta.get('deck'), str) else None,
                     str(documents_directory(meta))])
        log.debug(f"Copy theme '{meta['theme']}' -> '{dir_site}theme/'")
        warnings += filesystem.copy_directories(meta['theme'], dir_site / 'theme/')
    if only:        # a page that fails keeps its previous version
        meta['previous_pages'] = {}
        for page in built:
            if os.path.isfile(dir_site / page.site_html):
                with open(dir_site / page.site_html, 'rb') as fid:
                    meta['previous_pages'][page.site_html] = fid.read()
    source_transform = marker_transform(meta)
    warnings += pages.place(built, dir_site, project_assets=only, source_transform=source_transform)
    if only and meta.get('dependency_store'):
        meta['dependency_store'].refresh_assets(meta, built)
    for warning in warnings:
        log.warning(warning)
    directories = sorted({dir_site / page.site_directory for page in built}) if only else [dir_site]
    made, cached, errors = figures.build_figures(directories, meta['config_directory'] / figures.CACHE)
    if made or cached:
        log.keyvalue('info', f'Figures: {made} made, {cached} from the cache', indent_level=1)
    for script, error in errors:
        log.warning(f"Figure not made: {filesystem.shown(script, dir_site)}: {error}")

    log.debug(f"Found {len(selected)} template files")
    sitemap = generator_tool.extract_titles(selected)
    generator_tool.export_sitemap(sitemap, dir_site / 'sitemap/')
    meta['structure'] = generator_tool.export_structure(selected, dir_site / 'structure/',
                                                       meta.get('public_page_keys') or ())
    shutil.copy2(AGENTS_GUIDE, documents_directory(meta) / 'agents.md')
    built_set = set(built)
    meta['built'] = [entry for page, entry in zip(selected, meta['structure']) if page in built_set]
    return sitemap, write_credits_and_todo(meta, selected, log)


def write_credits_and_todo(meta, selected, log):
    """.structure/credits.md (origin of the pages, credits of the images)
    and .structure/todo.md (planned figures and slides), next to the
    configuration. Returns the credits of each page (lib/credits.py) and the
    errors of the pages whose credits are invalid ({page: message}: these
    pages fail)."""
    credits_of, errors = {}, {}
    for page in selected:
        try:
            credits_of[page] = credits.page_credits(page)
        except credits.CreditsError as exc:
            credits_of[page], errors[page] = {}, str(exc)
    documents = documents_directory(meta)
    text, credited, missing = credits.credits_markdown(selected, credits_of, meta['config_directory'],
                                                       meta['macros'])
    with open(documents / 'credits.md', 'w', encoding='utf-8', newline='\n') as fid:
        fid.write(text)
    planned_figures = credits.placeholders(selected)
    planned_slides = meta.get('planned_slides') or []
    with open(documents / 'todo.md', 'w', encoding='utf-8', newline='\n') as fid:
        fid.write(credits.todo_markdown(planned_figures, planned_slides, meta['config_directory']))
    log.debug(f'Credits: {credited} credited, {missing} image(s) without credit ({documents}/credits.md)')
    if planned_figures or planned_slides:
        log.keyvalue('info', f'To do: {len(planned_figures)} planned figure(s), {len(planned_slides)} planned '
                             f'slide(s) ({documents}/todo.md)', indent_level=1)
    return credits_of, errors


def discard_page(meta, page):
    """Remove the outputs of a page that failed (the template is kept in debug
    mode). Its previous version (--only) is restored at the end of the build
    (restore_previous_pages), not before the next stages."""
    paths = [page.site_html] + ([] if meta['debug'] else [page.site_template])
    for path in paths:
        full_path = meta['site_directory'] / path
        if os.path.isfile(full_path):
            os.remove(full_path)


def drop_failed_pages(meta, selected, failed):
    """Remove the pages that failed from meta['built']: the plugins that run
    after (mid_process) only see the pages generated."""
    entries = dict(zip(selected, meta['structure']))
    dropped = {id(entries[page]) for page in failed}
    meta['built'] = [entry for entry in meta['built'] if id(entry) not in dropped]


def restore_previous_pages(meta, failed):
    """--only: the pages that failed get their previous version back."""
    for page in failed:
        previous = meta.get('previous_pages', {}).get(page.site_html)
        if previous is not None:
            with open(meta['site_directory'] / page.site_html, 'wb') as fid:
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


def marker_transform(meta):
    """`(text, path) -> text` writing the source-map markers of a template of
    the project, or None when the build does not want them. The same function
    marks the pages (lib/pages.py) and the templates they include, so a block
    names the file it is written in."""
    if not meta.get('source_map'):
        return None
    tags = source_scan.value_tags(meta['macros'])
    def mark(text, path):
        source = source_map.source_label(path, meta['config_directory'], meta['source_directory'])
        return source_map.add_markers(text, source, tags)
    return mark


def jinja_environment(meta, selected, built):
    """Jinja environment: the templates of the pages to generate (as the
    plugins left them in the site), then the files of the sources (includes,
    imports: the project first, then the other projects), then the site (theme)."""
    dir_site = meta['site_directory']
    templates = {}
    for page in built:
        with open(dir_site / page.site_template, encoding='utf-8') as fid:
            templates[page.site_template] = fid.read()
    roots = [meta['source_directory']] + sorted(set(other_sources(selected).values()))
    loader = ChoiceLoader([DictLoader(templates)] + [FileSystemLoader(root) for root in roots]
                         + [FileSystemLoader(dir_site)])
    loader = TrackingLoader(loader, roots, marker_transform(meta))
    return Environment(loader=loader, cache_size=0, extensions=['jinja_markdown.MarkdownExtension'])


def render_jinja(meta, selected, built, sitemap, log, credits_of=None, errors=None):
    """Render the Jinja2 templates of the pages to generate (`built`, among the
    pages of the site `selected`); `errors`: {page: message} of the pages that
    already failed. Returns the list of pages that failed."""
    dir_site = meta['site_directory']
    env = jinja_environment(meta, selected, built)
    used = sitemap_keywords_used(env, [page.site_template for page in built])
    targets = {id_site: page.site_html for id_site, page in sitemap.items()
               if used is None or 'pathTo_' + id_site in used or 'linkTo_' + id_site in used}

    log.keyvalue('Found', f'{len(built)} template files')
    failed = []
    built_set = set(built)
    entries = dict(zip(selected, meta['structure']))
    credits_of = credits_of or {page: {} for page in selected}
    deck_credits = credits.all_credits(selected, credits_of)
    for k, page in enumerate(selected):
        if page not in built_set:
            continue
        if page in (errors or {}):
            log.error(errors[page])
            failed.append(page)
            discard_page(meta, page)
            continue
        links = {}
        for id_site, target in targets.items():
            url = page.path_to_root + target
            links['pathTo_' + id_site] = url
            links['linkTo_' + id_site] = f'<a href="{url}">{id_site}</a>'

        log.debug(f'- {page.site_template}')
        try:
            env.loader.used.clear()
            template = env.get_template(page.site_template)
            output_html = template.render({**meta['keywords'], **links, 'params': page.params,
                                           'page': entries[page],
                                           'credit': credits.credit_function(page, credits_of[page]),
                                           'credits': deck_credits,
                                           'pathToRoot': page.path_to_root, 'pageID': k})
        except Exception as e:
            log.error(f'Jinja2 error in {page.site_template}: {e}')
            failed.append(page)
            discard_page(meta, page)
            continue

        meta.setdefault('template_dependencies', {})[page.site_html] = sorted(env.loader.used | {str(page.src)})
        filesystem.write_file(dir_site / page.site_html, output_html)

    return failed


def load_project_design(meta):
    """The design of the project: design.yaml of the theme + 'design' of the configuration."""
    return design.load_design(meta['theme'], meta.get('design'), meta['config_directory'])


def render_lhtml(meta, selected, log, failed_before=()):
    """Run LHTML conversion on all rendered templates, with optional HTML tidy
    (not on the pages that failed before: `failed_before`). Returns the list
    of pages that failed."""
    tidy_options = {'doctype': 'html5', 'show-warnings': 'no', 'warn-proprietary-attributes': 'no'}

    tidylib.BASE_OPTIONS = {}
    failed = []

    skipped = set(failed_before)
    for page in selected:
        html_path = meta['site_directory'] / page.site_html

        if page in skipped or not os.path.isfile(html_path):
            # Jinja2 rendering failed for this page (error already reported)
            continue
        log.debug(f'- {html_path}')
        with open(html_path, 'r', encoding='utf-8') as fid:
            input_html = front_matter.split(fid.read())[0]   # LHTML 3 reads none

        # The macros of the design, the video variants; not `wrap-auto`: the
        # theme wraps the page (lib/wrap.py)
        options = {'macros': meta.get('macros'),
                   'media': video_cache.media(meta['site_directory'] / page.site_directory)}

        try:
            with python_warnings.catch_warnings(record=True) as caught:
                python_warnings.simplefilter('always')
                output_html = lhtml.run(input_html, options)
            for warning in caught:          # with the page they come from
                log.warning(f'{page.label}: {warning.message}')
            if meta.get('source_map'):
                output_html = source_map.apply(output_html)
            if meta.get('feedback'):
                output_html = feedback.add_script(output_html)
        except Exception as e:
            log.error(f'{html_path}: {e}')
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
            j2_path = meta['site_directory'] / page.site_template
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

    for local, name in sass_files:
        path_sass = dir_site / local / name
        css_txt = sass.compile(filename=path_sass)

        filesystem.write_file(path_sass.with_suffix('.css'), css_txt)

        os.remove(path_sass)


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

def clean_directories(meta):
    site_dir = meta['site_directory']
    if os.path.isdir(site_dir):
        shutil.rmtree(site_dir)
    meta['log'].plain('Directories cleaned\n')


# ---------------------------------------------------------------------------
# Render of files (--render)
# ---------------------------------------------------------------------------

def render_files(meta, files, log):
    """PNG of each file as the slides draw it, in <layout output>/render/
    (under its path relative to the configuration directory, or, for a file
    outside it, under _outside/<its directory>/), at the size of the slides
    of the layout report."""
    from pathlib import Path
    from lib.layout.measure import run_node
    try:
        output = layout_options.output_directory(meta) / 'render'
    except ConfigError as exc:
        log.error(str(exc))
        sys.exit(1)
    base = Path(meta['config_directory']).resolve()
    entries, targets = [], {}
    for name in files:
        path = Path(name).resolve()
        if not path.is_file():
            log.error(f'--render: no file {name}')
            sys.exit(1)
        relative = path.relative_to(base) if path.is_relative_to(base) \
            else Path('_outside', *[part.strip('/\\:') or '_' for part in path.parts])
        png = output / (str(relative) + '.png')
        if png in targets and targets[png] != path:
            log.error(f'--render: {name} and {targets[png]} would be written to the same {png}')
            sys.exit(1)
        targets[png] = path
        entries.append({'file': str(path), 'png': str(png)})
    options = layout_options.options_of(meta)
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as fid:
        json.dump(entries, fid)
        listing = fid.name
    try:
        run_node('render_file.js', [f'--input={listing}', f"--width={options['width']}",
                                     f"--height={options['height']}"], chrome=options['chrome'], log=log)
    except RuntimeError as exc:
        log.error(str(exc))
        sys.exit(1)
    finally:
        os.remove(listing)
    for entry in entries:
        log.keyvalue('info', f"{filesystem.shown(entry['file'])} -> {filesystem.shown(entry['png'])}")


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
    # data-lhtml-src="file:line" on the blocks (lib/source_map.py) in the builds for development
    meta['source_map'] = bool(args.layout or args.serve or args.watch)
    meta['feedback'] = bool(args.serve)         # comments on the render (lib/feedback.py)
    meta['analyse_layout'] = bool(args.layout)  # the layout analysis runs in the build (lib/layout/build.py)

    # Diagnostic mode takes precedence over --clean and never runs plugins.
    if args.check_config or not args.clean:
        paths, plugin_failures = resolve_plugins(meta, log)
        context.plugin_paths.extend(paths)
        if plugin_failures:
            sys.exit(1)
    if (meta['analyse_layout'] or (args.check_config and meta.get('layout'))) and not args.clean:
        # What the analysis will refuse, refused here: before the build, and
        # with --check-config, which builds nothing (lib/layout_options.py).
        # A project that neither asks for the analysis nor configures it is
        # not held to a configuration it does not have, and --clean, which
        # does not touch the reports, is not held to it either.
        try:
            layout_options.output_directory(meta)
            layout_options.validate(meta, log)
        except ConfigError as exc:
            log.error(str(exc))
            sys.exit(1)
    if args.render:
        render_files(meta, args.render, log)
        return
    if args.check_config:
        # The deck and the design are read (not the pages): errors before any build
        try:
            loaded_deck = load_deck(meta)
            loaded_design = load_project_design(meta)
            loaded_theme = theme.of(meta)
        except (deck.DeckError, design.DesignError, ConfigError) as exc:
            log.error(str(exc))
            sys.exit(1)
        print(yaml.safe_dump({
            'config_file': str(config_file),
            'source_directory': config.source_directory.as_posix(),
            'site_directory': config.site_directory.as_posix(),
            'theme': {'directory': config.theme.as_posix(), **loaded_theme},
            'deck': meta['deck'] if loaded_deck is None else {
                'file': meta['deck'] if isinstance(meta['deck'], str) else '(inline)',
                'slides': len(loaded_deck.entries),
                'sources': {name: root.as_posix() for name, root in loaded_deck.sources.items()}},
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
            # the pages of the deck, and the other pages of the project (excluded, planned)
            selected = select_pages(meta, log)
            listed = {p.src for p in selected}
            selected += [p for p in pages.discover(pages.Source(None, meta['source_directory']),
                                                   exclude=[meta['site_directory']]) if p.src not in listed]
            if args.only:
                selected = deck.named_pages(selected, args.only, other_sources(selected))
            loaded_design = load_project_design(meta)
        except (deck.DeckError, design.DesignError, ValueError) as exc:
            log.error(str(exc))
            sys.exit(1)
        lint_pages(selected, loaded_design, log, details=True)
        return

    built = None
    try:
        selected = select_pages(meta, log, scaffold=args.scaffold)
        meta['dependency_contexts'] = {p.site_html: dependencies.page_context(p) for p in selected}
        meta['source_roots'] = other_sources(selected)
        meta['dependency_store'] = dependencies.BuildStore(meta)
        built = None
        if args.only:
            # the pages its pointers name; whether the build may stay partial
            # is decided in one place, by the dependency store
            named = deck.named_pages(selected, args.only, other_sources(selected))
            log.keyvalue('info', f"--only: {', '.join(p.label for p in named)}", indent_level=1)
            built = meta['dependency_store'].expand(meta, selected, named)
            if built is None:
                # a full build (the pages of the site changed), but the layout report
                # measures only the pages named (and those without a report)
                meta['measure'] = meta.get('dependency_measure') or [p.site_html for p in named]
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
    each finding (path:line). Returns the findings {source path: [Finding]}."""
    linter = lint.Linter(loaded_design)
    found = {}
    for page in selected:
        if str(page.src) not in found:          # occurrences of a page: once
            found[str(page.src)] = linter.lint(page.scan, page.settings.get('layout'))
    total = sum(map(len, found.values()))
    if details:
        for src, findings in found.items():
            path = filesystem.shown(src)
            for f in findings:
                log.plain(f'{path}:{f.line}: {f.kind}: {f.text}\n    -> {f.advice}')
    pages_with = sum(1 for findings in found.values() if findings)
    summary = (f'{total} value(s) written by hand in {pages_with} of {len(found)} page(s)' if total
               else f'no value written by hand in {len(found)} page(s)')
    if details:
        log.plain(f'\nLint: {summary}')
    elif total:
        log.keyvalue('info', f'Lint: {summary} (python generate.py --lint)', indent_level=1)
    return found


@contextmanager
def stage(log, title):
    """A stage of the build, as the log shows it: its title, then its time."""
    log.title(title, pre='\n')
    log.tic()
    yield
    log.ok_elapsed()


def generate_site(meta, selected, built):
    """Generate the pages `built` among the pages of the site `selected` (all
    of them, except with --only)."""
    log = meta['log']
    plugin_failures = 0
    _plugin_modules.clear()
    log.display('[bold white]****************************', pre='\n')
    log.display('[bold white]  Start website generator')
    log.display('[bold white]****************************')
    log.keyvalue('info', f"Source: {meta['source_directory']}", indent_level=1)
    log.keyvalue('info', f"Plugins: {meta['plugin']}", indent_level=1)

    with stage(log, 'Data preparation'):
        meta['loaded_design'] = load_project_design(meta)
        meta['macros'] = design.lhtml_macros(meta['loaded_design'])
        sitemap, (credits_of, credit_errors) = prepare_data(meta, selected, built, log)
        # theme/css/design.css and .structure/design.md, always written (even
        # empty): the theme may link it, and --only must not keep a previous one
        path = design.write_design(meta, meta['loaded_design'])
        log.debug(f"Design: {len(meta['macros'])} macro(s), {path}")
        meta['lint_findings'] = {src: [f.as_dict() for f in findings]
                                 for src, findings in lint_pages(built, meta['loaded_design'], log).items()}

    with stage(log, 'Pre-process'):
        plugin_failures += run_plugins(meta, 'pre_process', log)
        # Core stages on the sources, after the extensions have written them:
        # the theme wraps what the content ends up being (lib/wrap.py), and the
        # headings of that content get their ids (lib/headings.py).
        headings.run(meta)
        wrap.run(meta)
        # Transcoded videos next to the assets, before LHTML writes the <video>
        # tags whose sources video_cache.media lists
        video_cache.run(meta)

    with stage(log, 'Convert HTML'):
        failed = render_jinja(meta, selected, built, sitemap, log, credits_of, credit_errors)
        if failed:
            log.error(f'{len(failed)} page(s) not generated (see errors above)')
        drop_failed_pages(meta, selected, failed)

    with stage(log, 'Mid-process'):
        plugin_failures += run_plugins(meta, 'mid_process', log)

    with stage(log, 'LHTML'):
        failed += render_lhtml(meta, built, log, failed_before=failed)

    # SASS compilation
    compile_sass(meta, log)

    if meta['only']:
        dependencies.refresh_runtime_files(meta, built)

    with stage(log, 'Post-process'):
        post_ran = not failed and not plugin_failures
        if post_ran:
            plugin_failures += run_plugins(meta, 'post_process', log)
            # Core stages on the built site: the menu of the theme, and the
            # index of a site that has none (lib/menu.py, lib/index_page.py)
            menu.run(meta)
            index_page.run(meta)

    # The layout analysis is part of the generator, not a plugin: it runs
    # once the pages and the theme are in place, and before the dependency
    # store records what each page used. A plugin that fails during the post
    # stage does not take it away: a build that went wrong is when the
    # report is worth reading, and the plugin that used to run after it
    # could not suppress it either.
    if meta['analyse_layout'] and post_ran:
        with stage(log, 'Layout analysis'):
            layout_build.run(meta)

    restore_previous_pages(meta, failed)
    log.plain()
    if failed:
        log.error(f'{len(failed)} page(s) failed (see errors above)')
    if plugin_failures:
        log.error(f'{plugin_failures} plugin error(s) (see errors above, use -d for details)')
    if failed or plugin_failures:
        raise RuntimeError('Page or plugin errors (see above)')
    if meta.get('dependency_store'):
        meta['dependency_store'].save(meta)


def main():
    if int(lhtml.__version__.split('.')[0]) < 3:
        # LHTML 2 ignores the `media` resolver and expands include:: on its own
        sys.exit('static_website_lhtml requires lhtml-markup >= 3.0 (pip install -U lhtml-markup)')
    args = parse_arguments()
    if args.serve or args.watch:
        from lib.development import develop
        develop(args, build_once)
    else:
        build_once(args)


if __name__ == '__main__':
    main()
