"""Static website generator built on LHTML.

Pipeline: copy sources → Jinja2 rendering → LHTML conversion → SASS compilation
with plugin hooks at pre/mid/post stages.
"""

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, FunctionLoader, TemplateError
from jinja2 import meta as jinja_meta
import tidylib
import yaml
import json
import os
import shutil
import tempfile
import argparse
import sys
import time
import traceback
from pathlib import Path

from lib import deck
from lib import credits
from lib import design
from lib import feedback
from lib import figures
from lib import filesystem
from lib import front_matter
from lib import generator_tool
from lib import lint
from lib import markdown_page
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
from lib.extensions import Extensions, ExtensionError
from lib import logger
from lib import pages
from lib import pdf_export
from lib import project
from lib.configuration import BuildContext, ConfigError, load_config, validate_paths
from lib import layout_options
from lib.build_output import links_out_of, staged_site
from lib.structure import documents_directory

import lhtml


PAGE_TEMPLATE = '<page:{}>'          # the file name Jinja gives a page template


class BuildFailed(Exception):
    """Pages or plugins failed: each said so where it failed."""


# Configuration & CLI

def parse_arguments():
    parser = argparse.ArgumentParser(description='Generate Website.')
    debug_group = parser.add_mutually_exclusive_group()
    debug_group.add_argument('-d', '--debug', action='store_true', default=None,
                        help='Display more information and keep temporary files.')
    debug_group.add_argument('--no-debug', dest='debug', action='store_false',
                             help='Disable debug mode configured in YAML.')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Display the stages of the build, their time, and what they did.')
    parser.add_argument('--strict', action='store_true',
                        help='A warning fails the build (exit code 1), as an error does.')
    parser.add_argument('-c', '--clean', action='store_true',
                        help='Clean the output directories.')
    parser.add_argument('-i', '--input_config',
                        help='Input yaml configuration file. Default=configure.yaml')
    parser.add_argument('--only', metavar='POINTER', action='append',
                        help='Generate only these pages (deck pointer: directory, file, glob; repeatable) '
                             'in the existing site; a full build when the pages of the site changed.')
    parser.add_argument('--target', metavar='NAME', action='append',
                        help='Build only these targets of the configuration (repeatable, or html,pdf); '
                             'all of them by default.')
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
    args.target = [t for value in args.target or [] for t in value.split(',') if t] or None
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
            log.info(f'Deck: created {filesystem.shown(path)}')
        return select_pages(meta, log)
    for warning in result.warnings:
        log.warning(f'Deck: {warning}')
    if not result.pages:
        log.warning('Deck: no page selected (the site will be empty)')
    for entry in result.missing:
        log.warning(f"Deck: '{entry.pointer}' ({entry.meta['title']}) has no source yet "
                    f"(--scaffold creates it)")
    log.detail(f'Deck: {result.summary(loaded_deck.duration)}')
    if (extra := result.over_time(loaded_deck.duration)) is not None:
        log.warning(f'Deck: {extra:g} min over the length of the talk ({loaded_deck.duration:g} min, '
                    f"key 'duration' of the deck)")
    if result.unlisted:
        names = ', '.join(p.label for p in result.unlisted[:5])
        more = f' and {len(result.unlisted) - 5} more' if len(result.unlisted) > 5 else ''
        log.detail(f'Deck: {len(result.unlisted)} page(s) not in the deck, not generated: {names}{more}')
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
        log.debug(f"Copy theme '{meta['theme']}' -> '{dir_site / 'theme'}'")
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
        log.detail(f'Figures: {made} made, {cached} from the cache')
    for script, error in errors:
        log.warning(f"Figure not made: {filesystem.shown(script, dir_site)}: {error}")

    log.debug(f"Found {len(selected)} template files")
    sitemap = generator_tool.extract_titles(selected, meta['macros'])
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
    documents = documents_directory(meta, scoped=True)
    text, credited, missing = credits.credits_markdown(selected, credits_of, meta['config_directory'],
                                                       meta['macros'])
    with open(documents / 'credits.md', 'w', encoding='utf-8', newline='\n') as fid:
        fid.write(text)
    planned_figures = credits.placeholders(selected, meta['macros'])
    planned_slides = meta.get('planned_slides') or []
    with open(documents / 'todo.md', 'w', encoding='utf-8', newline='\n') as fid:
        fid.write(credits.todo_markdown(planned_figures, planned_slides, meta['config_directory']))
    log.debug(f'Credits: {credited} credited, {missing} image(s) without credit ({documents}/credits.md)')
    if planned_figures or planned_slides:
        log.info(f'To do: {len(planned_figures)} planned figure(s), {len(planned_slides)} planned '
                 f'slide(s) ({filesystem.shown(documents / "todo.md")})')
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
            variables = jinja_meta.find_undeclared_variables(ast)       # compiles: an unknown filter
            references = list(jinja_meta.find_referenced_templates(ast))
        except TemplateError:
            continue                    # reported when the page is rendered
        used.update(n for n in variables if n.startswith(('pathTo_', 'linkTo_')))
        for reference in references:
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
    # A page template is named `<page:a/index.html.j2>`: a Jinja error in it,
    # or in a page it includes, says which page (jinja_place)
    pages = FunctionLoader(lambda name: (templates[name], PAGE_TEMPLATE.format(name), lambda: True)
                           if name in templates else None)
    loader = ChoiceLoader([pages] + [FileSystemLoader(root) for root in roots]
                         + [FileSystemLoader(dir_site)])
    loader = TrackingLoader(loader, roots, marker_transform(meta))
    env = Environment(loader=loader, cache_size=0, extensions=['jinja_markdown.MarkdownExtension'])
    env.filters['markdown_page'] = markdown_page.convert         # the content of a Markdown page
    return env


def render_jinja(meta, selected, built, sitemap, log, credits_of=None, errors=None):
    """Render the Jinja2 templates of the pages to generate (`built`, among the
    pages of the site `selected`); `errors`: {page: message} of the pages that
    already failed. Returns the list of pages that failed."""
    dir_site = meta['site_directory']
    env = jinja_environment(meta, selected, built)
    used = sitemap_keywords_used(env, [page.site_template for page in built])
    targets = {id_site: page.site_html for id_site, page in sitemap.items()
               if used is None or 'pathTo_' + id_site in used or 'linkTo_' + id_site in used}

    log.detail(f'{len(built)} page(s) to render')
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
            log.error(f'Jinja: {e}', jinja_place(e, page, meta, {p.site_template: p for p in selected}))
            failed.append(page)
            discard_page(meta, page)
            continue

        meta.setdefault('template_dependencies', {})[page.site_html] = sorted(env.loader.used | {str(page.src)})
        filesystem.write_file(dir_site / page.site_html, output_html)

    return failed


def load_project_design(meta):
    """The design of the project: design.yaml of the theme + 'design' of the configuration."""
    return design.load_design(meta['theme'], meta.get('design'), meta['config_directory'])


def lhtml_place(text, problem, page, base=None):
    """Where a problem LHTML found in `text` (a page as Jinja wrote it) is in
    the source (a problem that is not LHTML's has no line: the page)."""
    return source_map.place(text, getattr(problem, 'line', None), getattr(problem, 'column', None),
                            page.src, filesystem.shown(page.src), base)


def jinja_place(error, page, meta, pages):
    """Where a Jinja error is: a line of the template it names - the source of
    a page (`pages`: {site template: page}), the theme or a file of the
    sources, never their copy in the site being built."""
    name, line = getattr(error, 'filename', None), getattr(error, 'lineno', None)
    if line is None:            # while rendering: the last frame of a template
        frames = [(f.f_code.co_filename, n) for f, n in traceback.walk_tb(error.__traceback__)
                  if f.f_code.co_filename.startswith('<page:') or f.f_code.co_filename.endswith(('.html', '.j2'))]
        if frames:
            name, line = frames[-1]
    if line is None or name is None:
        return filesystem.shown(page.src)
    if name.startswith('<page:'):
        owner = pages.get(name[len('<page:'):-1], page)
        with open(meta['site_directory'] / owner.site_template, encoding='utf-8') as fid:
            return source_map.place(fid.read(), line, None, owner.src, filesystem.shown(owner.src),
                                    meta['config_directory'])
    path = Path(name).resolve()
    site = Path(meta['site_directory']).resolve()
    if path.is_relative_to(site / 'theme'):
        path = Path(meta['theme']) / path.relative_to(site / 'theme')
    elif path.is_relative_to(site):
        path = Path(meta['source_directory']) / path.relative_to(site)
    return f'{filesystem.shown(path)}:{line}'


def render_lhtml(meta, selected, log, failed_before=()):
    """Run LHTML conversion on all rendered templates, with optional HTML tidy
    (not on the pages that failed before: `failed_before`). A Markdown page
    was converted by Jinja (lib/markdown_page.py): LHTML does not read it.
    Returns the list of pages that failed."""
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

        # The macros of the design, the video variants, the line breaks; not
        # `wrap-auto`: the theme wraps the page (lib/wrap.py)
        media = video_cache.media(meta['site_directory'] / page.site_directory)

        try:
            output_html = input_html
            if page.markup == 'lhtml':
                document = lhtml.parse(input_html, macros=meta.get('macros'), warn=False)
                output_html = lhtml.render(document, line_breaks=meta.get('line_breaks', False), media=media)
                for problem in document.problems:   # in the order of the page, where they are in the source
                    log.warning(problem, lhtml_place(input_html, problem, page, meta['config_directory']))
            if meta.get('source_map'):
                output_html = source_map.apply(output_html)
            if meta.get('feedback'):
                output_html = feedback.add_script(output_html)
        except Exception as e:
            for problem in getattr(e, 'problems', ()):     # those LHTML found before its error
                log.warning(problem, lhtml_place(input_html, problem, page, meta['config_directory']))
            log.error(e, lhtml_place(input_html, e, page, meta['config_directory']))
            failed.append(page)
            discard_page(meta, page)
            continue

        if meta['use_tidy']:
            tidy_html, error = tidylib.tidy_document(output_html, options=tidy_options)
            if error:
                log.error(f'Tidy: {error}', filesystem.shown(html_path))
                for k, line in enumerate(output_html.split('\n')):
                    log.debug(f'{k + 1}: {line}')
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

def clean_directories(site_directory, log):
    if os.path.isdir(site_directory):
        shutil.rmtree(site_directory)
    log.info(f'Cleaned {filesystem.shown(site_directory)}')


# ---------------------------------------------------------------------------
# Render of files (--render)
# ---------------------------------------------------------------------------

def render_files(meta, files, log):
    """PNG of each file as the slides draw it, in <layout output>/render/
    (under its path relative to the configuration directory, or, for a file
    outside it, under _outside/<its directory>/), at the size of the slides
    of the layout report."""
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
        log.info(f"{filesystem.shown(entry['file'])} -> {filesystem.shown(entry['png'])}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_once(args):
    """Build the project: each of its decks for each of its targets
    (lib/project.py), one after the other. A build that fails does not stop
    the next ones; the command fails if one did."""
    try:
        config, config_file, warnings = load_config(
            args.input_config or 'configure.yaml', debug_override=args.debug)
        validate_paths(config, config_file, require_inputs=not args.clean or args.check_config)
        cleaning = args.clean and not args.check_config      # --check-config diagnoses, and deletes nothing
        # the decks are not looked for: cleaning needs no sources (they may be gone)
        builds = [] if cleaning else project.plan(config, args.only, args.target)
        if cleaning and args.target:
            project.check_targets(config, args.target)
    except ConfigError as exc:
        logger.Logger().error(str(exc))
        sys.exit(1)

    log = logger.Logger(verbose=args.verbose, debug=config.debug)
    for warning in warnings:
        log.warning(warning)
    if cleaning:
        clean_directories(config.site_directory, log)
        return
    if config.decks and any(pages.is_template(p.name) for p in config.source_directory.iterdir()):
        log.warning(f"decks: directories: the pages at the top of '{filesystem.shown(config.source_directory)}' "
                    f"belong to no deck and are not built")
    if args.render:                 # no build: the files are rendered once
        builds = builds[:1]
    elif args.lint:                 # the sources of a deck are the same for each of its targets
        builds = [b for k, b in enumerate(builds) if b.deck not in {c.deck for c in builds[:k]}]
    failed = []
    strict_failed = bool(args.strict and log.counts['warning'])     # of the configuration, before any build
    if strict_failed and not (args.check_config or args.lint or args.render):
        # a refused build publishes nothing: none is made (the modes that
        # build nothing still diagnose, and fail at the end)
        log.error(f"{log.counts['warning']} warning(s) with --strict: nothing built")
        raise SystemExit(1)
    for build in builds:
        if build.label and log.verbose and not args.check_config:     # --check-config prints YAML only
            log.info(f'[{build.label}]')
        if not build_site(args, build, config_file, log):
            failed.append(build.label or 'the site')
    if failed or strict_failed:
        if failed and len(builds) > 1:
            log.error(f"{len(failed)} of {len(builds)} builds failed: {', '.join(failed)}")
        raise SystemExit(1)


def build_site(args, build, config_file, log):
    """Build one deck for one target. Returns whether it succeeded."""
    config, only = build.config, build.only
    context = BuildContext(config, config_file, args, log)
    meta = context.meta
    meta['deck'] = deck.deck_source(args.deck, config.deck, config_file.parent)
    # data-lhtml-src="file:line" on the blocks (lib/source_map.py) in the builds for development
    meta['source_map'] = bool(args.layout or args.serve or args.watch)
    meta['feedback'] = bool(args.serve)         # comments on the render (lib/feedback.py)
    meta['analyse_layout'] = bool(args.layout)  # the layout analysis runs in the build (lib/layout/build.py)
    meta['export_name'] = build.export_name     # the PDF of a deck (lib/pdf_export.py)
    meta['build_scope'] = build.scope           # its state, apart from the other builds
    start, warnings_before = time.time(), log.counts['warning']

    # Diagnostic mode takes precedence over --clean and never runs plugins.
    if args.check_config or not args.clean:
        paths, plugin_failures = resolve_plugins(meta, log)
        context.plugin_paths.extend(paths)
        if plugin_failures:
            return False
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
            return False
    if args.render:
        render_files(meta, args.render, log)
        return True
    if args.check_config:
        # The deck and the design are read (not the pages): errors before any build
        try:
            loaded_deck = load_deck(meta)
            loaded_design = load_project_design(meta)
            loaded_theme = theme.of(meta)
        except (deck.DeckError, design.DesignError, ConfigError) as exc:
            log.error(str(exc))
            return False
        print(yaml.safe_dump({
            **({'build': {'deck': build.deck, 'target': build.target}} if build.label else {}),
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
            'use_tidy': config.use_tidy,
        }, sort_keys=False, explicit_start=bool(build.label)))
        return True
    if args.lint:
        try:
            # the pages of the deck, and the other pages of the project (excluded, planned)
            selected = select_pages(meta, log)
            listed = {p.src for p in selected}
            selected += [p for p in pages.discover(pages.Source(None, meta['source_directory']),
                                                   exclude=[meta['site_directory']]) if p.src not in listed]
            if only:
                selected = deck.named_pages(selected, only, other_sources(selected))
            loaded_design = load_project_design(meta)
        except (deck.DeckError, design.DesignError, ValueError) as exc:
            log.error(str(exc))
            return False
        lint_pages(selected, loaded_design, log, details=True)
        return True

    built = None

    def strict():
        """--strict: a warning fails the build, before its site is published."""
        if args.strict and log.counts['warning'] > warnings_before:
            raise BuildFailed(f"{log.counts['warning'] - warnings_before} warning(s) with --strict")
    try:
        selected = select_pages(meta, log, scaffold=args.scaffold)
        meta['dependency_contexts'] = {p.site_html: dependencies.page_context(p) for p in selected}
        meta['source_roots'] = other_sources(selected)
        meta['dependency_store'] = dependencies.BuildStore(meta)
        built = None
        if only:
            # the pages its pointers name; whether the build may stay partial
            # is decided in one place, by the dependency store
            named = deck.named_pages(selected, only, other_sources(selected))
            log.detail(f"--only: {', '.join(p.label for p in named)}")
            built = meta['dependency_store'].expand(meta, selected, named)
            if built is None:
                # a full build (the pages of the site changed), but the layout report
                # measures only the pages named (and those without a report)
                meta['measure'] = meta.get('dependency_measure') or [p.site_html for p in named]
        meta['only'] = built is not None
        if meta['only'] and (links := links_out_of(meta['site_directory'])):
            path, target = links[0]
            what = ('a file with another hard link' if isinstance(target, str)
                    else f"a symbolic link to '{filesystem.shown(target)}', out of the site")
            raise BuildFailed(f"Unsafe output: '{filesystem.shown(path)}' is {what}; --only writes "
                              f"in the site: remove it (or build without --only)")
        meta['strict'] = strict         # checked before the pages are kept (generate_site)
        if meta['only'] and args.strict:
            # a refused build publishes nothing: built in a copy of the site
            with staged_site(meta, copy=True):
                count = generate_site(meta, selected, built)
        elif meta['only']:
            # In the site itself: copying it into a staging directory would
            # cost more than the pages generated
            count = generate_site(meta, selected, built)
        else:
            with staged_site(meta):
                count = generate_site(meta, selected, selected)
    except Exception as exc:
        kept = '' if built is not None else ' (previous site kept)'
        log.error(f"{build.label + ': ' if build.label else ''}build failed{kept}: {exc}")
        if not isinstance(exc, BuildFailed):
            log.debug(traceback.format_exc())
        return False
    warnings = log.counts['warning'] - warnings_before
    output = meta.get('exported') or config.site_directory
    log.info(f"{build.label + ': ' if build.label else ''}{count} page(s) built in {time.time() - start:.1f}s"
             f"{f', {warnings} warning(s)' if warnings else ''} -> {filesystem.shown(output)}")
    return True


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
                log.info(f'{path}:{f.line}: {f.kind}: {f.text}\n    -> {f.advice}')
    pages_with = sum(1 for findings in found.values() if findings)
    summary = (f'{total} value(s) written by hand in {pages_with} of {len(found)} page(s)' if total
               else f'no value written by hand in {len(found)} page(s)')
    if details:
        log.info(f'\nLint: {summary}')
    elif total:
        log.detail(f'Lint: {summary} (generate.py --lint)')
    return found


def generate_site(meta, selected, built):
    """Generate the pages `built` among the pages of the site `selected` (all
    of them, except with --only)."""
    log = meta['log']
    try:
        extensions = Extensions(meta['plugin_paths'])        # the plugins (lib/extensions.py)
    except Exception as exc:
        raise BuildFailed(f'plugin: {type(exc).__name__}: {exc}' if not isinstance(exc, ExtensionError)
                          else str(exc)) from exc
    log.detail(f"Source: {filesystem.shown(meta['source_directory'])}, plugins: {meta['plugin']}")

    with log.stage('Data preparation'):
        meta['loaded_design'] = load_project_design(meta)
        meta['macros'] = design.lhtml_macros(meta['loaded_design'])
        sitemap, (credits_of, credit_errors) = prepare_data(meta, selected, built, log)
        # theme/css/design.css and .structure/design.md, always written (even
        # empty): the theme may link it, and --only must not keep a previous one
        path = design.write_design(meta, meta['loaded_design'])
        log.debug(f"Design: {len(meta['macros'])} macro(s), {path}")
        meta['lint_findings'] = {src: [f.as_dict() for f in findings]
                                 for src, findings in lint_pages(built, meta['loaded_design'], log).items()}

    with log.stage('Pre-process'):
        pages_of = {id(entry): page for page, entry in zip(selected, meta['structure'])}

        def run_extensions(stage):
            """A stage of the extensions; the pages it failed leave the build."""
            count, entries = extensions.run(stage, meta, log)
            pages = [pages_of[id(entry)] for entry in entries]
            for page in pages:
                discard_page(meta, page)
            drop_failed_pages(meta, selected, pages)
            return count, pages

        plugin_failures, failed = run_extensions('prepare')
        count, pages = run_extensions('pre_process')
        plugin_failures, failed = plugin_failures + count, failed + pages
        # Core stages on the sources, after the extensions have written them:
        # the theme wraps what the content ends up being (lib/wrap.py), and the
        # headings of that content get their ids (lib/headings.py).
        headings.run(meta)
        wrap.run(meta)
        # Transcoded videos next to the assets, before LHTML writes the <video>
        # tags whose sources video_cache.media lists. Not for a PDF: a page
        # shows one frame, and Chrome loads the source faster than a variant
        export = theme.of(meta)['export']
        if export == 'pdf':
            pdf_export.remove_video_controls(meta)
        else:
            video_cache.run(meta)

    with log.stage('Convert HTML'):
        failed += render_jinja(meta, selected, [p for p in built if p not in failed], sitemap, log,
                               credits_of, credit_errors)
        drop_failed_pages(meta, selected, failed)

    with log.stage('Mid-process'):
        count, pages = run_extensions('mid_process')
        plugin_failures, failed = plugin_failures + count, failed + pages

    with log.stage('LHTML'):
        failed += render_lhtml(meta, built, log, failed_before=failed)

    # SASS compilation
    compile_sass(meta, log)

    if meta['only']:
        dependencies.refresh_runtime_files(meta, built)

    with log.stage('Post-process'):
        post_ran = not failed and not plugin_failures
        if post_ran:
            count, pages = run_extensions('post_process')
            plugin_failures, failed = plugin_failures + count, failed + pages
            # Core stages on the built site: the menu of the theme, and the
            # index of a site that has none (lib/menu.py, lib/index_page.py)
            menu.run(meta)
            index_page.run(meta)
            if export == 'pdf':          # once the site is complete, menu included
                pdf_export.export(meta)

    # The layout analysis is part of the generator, not a plugin: it runs
    # once the pages and the theme are in place, and before the dependency
    # store records what each page used. A plugin that fails during the post
    # stage does not take it away: a build that went wrong is when the
    # report is worth reading, and the plugin that used to run after it
    # could not suppress it either.
    if meta['analyse_layout'] and post_ran:
        with log.stage('Layout analysis'):
            layout_build.run(meta)

    if not failed and not plugin_failures and meta.get('strict'):
        try:
            meta['strict']()            # --strict: a warning fails the build ...
        except BuildFailed:
            restore_previous_pages(meta, built)     # ... and --only keeps none of its pages
            raise
    restore_previous_pages(meta, failed)
    if failed or plugin_failures:
        raise BuildFailed(', '.join(f'{n} {what}' for n, what in ((len(failed), 'page(s) failed'),
                                                                 (plugin_failures, 'plugin error(s)')) if n))
    if meta.get('dependency_store'):
        meta['dependency_store'].save(meta)
    return len(built)


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
