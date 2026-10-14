# Architecture: core, themes, extensions, targets

Design note for the next major version. Nothing here is implemented yet. It
records what the current structure costs, the rules used to decide where each
piece belongs, and the target they lead to.

**Compatibility is not a constraint.** This is a major version: a
configuration of the previous one may stop working, provided the generator
says so with an explicit error. The goal is a smaller core, a smaller
extension surface, and a layout analysis that stands on its own as a product
for an LLM, not a side effect of a build.


## 1. The rules

An earlier draft used a single question - "remove it: is the site still
correct?". It does not work. "The site" is always *this* site with *this*
theme, so the question only measures whether the bundled defaults break, and
every bundled default comes out as core. It also contradicts switches that
already exist (`title_id: true` turns `title_submenu` off, and the theme
degrades to a hidden column), and it answers differently per project: a
project whose `pre_include` file defines the macros every page imports is
broken without that extension.

Three questions, asked in order, each answerable without naming a project:

1. **Who names it?** If the generator's own output contract names it
   (`structure/`, the sitemap, the page HTML), it is **core**. If a *theme*
   names it, it belongs to the **theme contract**: the theme declares, the
   core provides. If only a *project* names it, it is an **extension**.
2. **Does it change what a later stage reads, or only add a result?**
   Anything that rewrites a page template or the HTML before a later stage
   reads it is a **stage with a declared position** - inside the core, or an
   extension at that position. Anything that only produces a result is a
   **target** (it renders and delivers) or an **analysis** (it inspects what
   a target renders): see section 4.3.
3. **Is it reachable without a build?** Then it is a **tool**, not a stage
   (`--render` and `--lint` already are).

Question 2 is the one the current design cannot express at all, and it is the
one that explains the ordering bugs of section 2.

| Plugin | Belongs to |
|---|---|
| `menu.py` | theme contract: data the theme declares it needs, rendered by the core |
| `title_submenu.py` | core stage, keeping the `title_id:` switch it already has |
| `auto_wrap.py` | core stage, **only if** the template path comes from the theme (it hard-codes `theme/template/base.html` today) |
| `redirection_first_page.py` | core option `index: redirect / own page / none` - a project choice, not core-ness |
| `pre_include.py` | extension, position: before wrapping |
| `code_include.py` | extension, position: after Jinja, before LHTML |
| `cache_video.py` | **core asset stage with a pluggable converter** (see section 4) |
| `layout_report.py` | analysis of a target: it changes the pipeline, it does not only read the site |
| `generate_pdf.py` | target: own theme, own source transform, own deliverables |

Note what no rule says: none of these removals makes the *build* fail. Even
`plugin: []` exits with success. The breakage is always in the produced site,
which is why these dependencies stayed invisible.


## 2. What the current structure costs

Facts, each checked against the code (line numbers as of this note).

**The core knows two plugins by their file name, in three places.**
`generate.py:134-140` (`add_layout_plugin`) inserts `layout_report.py` before
`generate_pdf.py` by testing `p.endswith(...)`; `generate.py:639` tests the
same name again to validate the report output directory; `generate.py:569`
imports two private symbols of the plugin, `from plugins.layout_report import
_options, _run_node`, for `--render`. A fourth place is in
`lib/configuration.py:238-263`, a function dedicated to that one plugin.

**A plugin performs the publication step.** `plugins/generate_pdf.py:83`,
`shutil.rmtree(site_dir)`. `lib/build_output.py:19-20` has to know about it:
"PDF-only exports may intentionally remove their staging site", followed by
`if staging.is_dir()`. The ordering constraint documented in the README ("put
`generate_pdf.py` last") exists only because of this, and nothing checks it.

**The order of two plugins silently changes the output.** With `pre_include`
then `auto_wrap`, the included text lands inside the document; in the reverse
order it lands before `<!DOCTYPE html>`, outside the document, which puts the
browser in quirks mode. No error, no warning. Pinned by
`tests/test_plugin_order.py`.

**The plugin contract is wide.** The nine plugins touch 16 keys of `meta`
directly (15 read, plus `headings`, which `title_submenu` writes), about 20
counting what `lib.structure` and `layout_output_directory(meta)` read on
their behalf. Several are internal build state: `loaded_design`, `measure`,
`published_site_directory`, `plugin_paths`, `config_file`. And `headings` is
written by a plugin and read by nobody: dead runtime state to drop.

**The analysis code is trapped inside a plugin**, and the merge of
`split-agent` made it larger rather than less trapped: of the 1516 lines of
`plugins/layout_report.py`, lines 70 to 1230 - analysis, alignment and
density, Markdown rendering, 1161 lines - still use no `meta` at all, and
their single tie to `lib` is `analyse_design` from `lib/design_checks.py`,
which is itself a pure analysis module and belongs in the same place. Only
the last 285 lines are plugin glue. Because that code has no legitimate home,
three places reach into it by path: `tools/style_profile.py:36-39` inserts
two entries in `sys.path` and uses 12 symbols, 4 of them private;
`tests/test_layout_report.py:10` loads the file by location; the core imports
it as a package.

**Themes depend on plugins, and nothing says so.** All three themes need
`menu.py` (`{{TOC}}` in `themes/*/js/menu.js`); `webpage-frame` also needs
`title_submenu.py`. A default configuration produced an empty summary column
until `title_submenu.py` was added to the default list.

**Three defects found while writing this note, now fixed.** Each one is a
symptom of a missing contract, not bad luck:

- The menu published **every** page setting into `theme/js/menu.js`, a file
  served to every visitor: a `notes:` or `message:` written for the author
  was readable in the site. Fixed with a declared list of keys
  (`plugins/menu.py`). Missing contract: *which page settings a theme may
  see*. `structure/structure.yaml` is still written into the site with every
  setting - see the open questions.
- `RESERVED AREA` reported 33 problems on the three example pages, all false:
  the reserved zone was the union of the boxes of all visible descendants of
  the navigation, and a navigation with parts at two corners covers the whole
  page. Fixed by keeping one rectangle per part that paints - and that fix,
  correct on the example, reported a block five times on a real deck, once
  per icon of the navigation, until the findings were grouped per block.
  Missing contract: *what the theme reserves*. Worth remembering as the
  argument for section 5.3: three example pages cannot calibrate a check.
- With the default `root: 'body'` and the bundled theme, every page was
  measured as a **single block**, so every per-block check was empty while
  the report looked healthy; the right value was documented in the plugin's
  own docstring. Fixed with a warning. The real fix is for the theme to
  declare its content root.


## 3. Observable guarantees, decided before the components move

Reorganising the code does not by itself make a build more trustworthy. Two
guarantees have to be written down first, because they constrain every
decision that follows. Both are weak today.

### 3.1 A partial build agrees with a full build

`--only` is the mode used most, and it is a second, implicit pipeline: it
skips the copy of the sources and of the theme (`generate.py:264-269`), keeps
the previous bytes of the pages it does not build, builds in place instead of
in a staging directory (`:700-706`), and changes what the layout analysis
measures (`:699`).

The rule: **a partial build produces, for everything it touches and
everything that depends on it, the same result as a full build. When the
generator cannot determine those dependencies, it widens the build and says
why.**

Most of this now exists, and it arrived with the merge of `split-agent`:
`lib/dependencies.py` fingerprints the inputs of each page (its assets, the
whole theme, the design, the configuration, the plugins) in
`.verification/builds.json`. `BuildStore.expand()` adds to a partial build
the pages whose inputs changed, and when the change touches a shared input -
or anything untracked - it returns to a full build and says so. Checked: a
`--only a` after editing a file of the theme prints "shared inputs changed or
untracked; full build". The conservative fallback is the right one.

What is left is the part that makes it a guarantee rather than a behaviour:

- it is not pinned as a property. A test should state it from outside - the
  same sources, built fully and partially, give the same site - rather than
  test the fingerprints;
- `only_pages()` keeps its own check (the list of pages), so two mechanisms
  decide the same thing in two places;
- `restore_previous_pages()` restores the HTML bytes of a page that failed,
  and nothing else it may have written;
- an external resource is reported as untracked, which is honest, and makes
  every build with one a full build. Worth measuring on a real deck.

### 3.2 What is published, and what stays private

The site directory is both the deliverable and the build state, and the
build state is published with it. Today `structure/structure.yaml` and
`structure.json` are written inside the site with **every** page setting
(`lib/generator_tool.py:103-110`: `{'title': ..., **page.settings, ...}`),
including the `notes:` an author writes for themselves - and with `src`, the
**absolute path of the source on the author's machine**
(`/Users/.../example/content/01_introduction/index.html.j2` in the example
site). Filtering what the theme receives, as the menu now does, is not
enough: the files the generator copies or exports must obey the same rule.

The same applies to the documents the build writes next to them:
`structure/agents.md` (the procedure for an agent), `structure/design.md`
(the macros and tokens of the theme) and `structure/todo.md` (the planned
figures) are working documents of the author, published with the slides
because the build had nowhere else to put them. They belong with the
diagnostics, not in the site.

The rule: **build state lives outside the site; what is published is an
explicit list.** Then `publish:` stops being a boolean. A PDF target
publishes `slides.pdf` and `images/`, keeps the HTML as an intermediate, and
keeps the diagnostics (`.layout/`, the lint) outside the published tree -
three different answers that `publish: false` conflates.

## 4. Where each piece goes

### 4.0 The theme contract

The theme is the third party the decomposition kept circling without naming.
It decides whether `menu` exists at all (`{{TOC}}`), supplies the template
`auto_wrap` hard-codes, sets what the measurement takes as its root, reserves
the areas the content must not cover, and selects the PDF variant. Three of
the defects above are theme contracts that were never written down.

A theme declares:

- which of its files are **rendered once per build** and with what data
  (`menu.js` with the table of contents), which are **rendered per page**
  (`template/base.html`), and which are **copied verbatim** (everything else);
- which **page settings** it may receive (the rest never reaches the site);
- its **content root** and its **reserved areas**, for the measurement;
- its **base template**, for the wrapping stage;
- its **injection points**: where a project may add a script or a style to
  every page (today `keywords: jsAbs`), and what such a script may read -
  the table of contents, the number of the page - as a documented interface.
  Without it the contract is a global variable: a timer script reading `toc`
  and `page_index`, which `menu.js` happens to define, breaks silently the
  day the menu becomes a core stage.

### 4.1 Pipeline stages - core, not switchable

Page discovery, deck, page wrapping (today `auto_wrap`, with the template
from the theme), Jinja rendering, heading ids and per-page summary (today
`title_submenu`, keeping `title_id:`), LHTML, SASS, assets including the
video cache (today `cache_video`), structure export, credits, lint, index
page (today `redirection_first_page`, as `index:`).

**`menu.py` does not disappear into Jinja.** The earlier draft guessed that
rendering the theme assets through Jinja would remove the stage. It would
not, for four checkable reasons: `katex.min.js` contains `{{` sequences in
all three themes, so a blanket render is a syntax error or a corrupted maths
renderer; the themes are overwhelmingly binary (fonts, images), so the core
needs a list of renderable files anyway - which is the knowledge `menu.py`
holds today, moved into the theme manifest; `template/base.html` must be
rendered *per page*, not once; and `--only` skips the theme copy entirely
(`generate.py:266`), which is exactly why `menu.py` restarts from the theme's
own template (its comment says so). The stage survives; the plugin does not.

**`cache_video` is not an extension.** `lhtml/export_html.py:109` hard-codes
`CACHE_VIDEO_DIR = 'cache_video_codecs/'` and probes the filesystem for it
when it writes a `<video>`; `plugins/cache_video.py:15` repeats the same
literal. The plugin does not add content: it changes what a *core* stage
emits, through a side channel neither side declares, and it must run before
LHTML for that reason. It belongs in the core as an asset stage with a
pluggable converter, and the directory name belongs in the contract. (A
second spelling exists in the repository, `video_codecs/`, used by
`tools/process_video.py` and by the example assets.)

### 4.2 Extensions - the plugins, and nothing else

`pre_include`, `code_include`. Specific to a project, optional, each with a
declared position in the pipeline.

**What the contract really is.** An earlier draft claimed the contract
shrinks on its own because the internal keys are read by components that
become core. That is true of the keys, and it measures the wrong thing. After
the split the extensions still read `structure` and `built` (through
`lib.structure`), and the dangerous part would be untouched: **the right to
open and rewrite the page files on disk, mid-build**. `pre_include` rewrites
the template in `pre_process`; `code_include` rewrites the rendered HTML
between Jinja and LHTML.

Declaring a position orders those rewrites; it does not reduce them. So the
contract is not "a position plus a file handle", it is a transformation:

```
content + a limited context -> transformed content + diagnostics
```

The engine keeps every write. An extension that cannot touch the file system
is testable on a string, cannot leave a half-rewritten template behind when
it fails, and cannot interfere with another target rendering the same sources
in the same run - which is what makes several targets possible at all. The
key count goes from about 20 to a handful; the write right goes from
undeclared to absent, and that is the actual improvement.

### 4.3 Targets, analyses and presets - not "exports after the pipeline"

Calling these exports was wrong, and checkably so. `generate_pdf` has a
`pre_process` that rewrites every template before Jinja
(`plugins/generate_pdf.py:29-31`), needs its own theme (`themes/slides-pdf`),
and publishes by deleting. `--layout` turns on `source_map` for the whole
build (`generate.py:627`), sets `meta['measure']` (`:699`), and depends on
the lint running inside `generate_site` (`:756`) so the report can read
`meta['lint_findings']`. Neither consumes a finished site.

But they are not the same kind of thing either, and an earlier draft put them
both under one word, "profile" - which this note also used for sets of
thresholds. Three names, three jobs:

- A **target** is what is rendered and delivered: a theme, the source
  transforms it needs, and its deliverables. `html` and `pdf` are targets.
  "HTML and PDF in one run" is two targets over one source scan, impossible
  today with a single `theme:` key.
- An **analysis** inspects a target: `lint`, `layout`. An analysis may
  require the build to be prepared for it - the layout analysis needs the
  source map - but needing preparation does not make it a deliverable.
  "Check the HTML and the PDF" is then one phrase, not two pipelines.
- A **preset** is a named combination of a target and its analyses, for the
  user: what `--layout` and `--pdf` select today.

**An analysis that fails does not fail its target.** A failure of the
measurement used to count as a plugin failure, so the build raised and the
site was not published: a missing Chrome threw away a correct build ("Build
failed; previous site preserved"). The layout plugin now catches its own
failures and says the report was not produced, which is the behaviour this
separation makes structural rather than a precaution inside one plugin. An
unsafe output directory stays fatal: that is a configuration error, not a
failure of the analysis. A target either renders or does not; an analysis
reports, or reports that it could not run.

Those three replace `add_layout_plugin`, the three file-name tests, the
`if staging.is_dir()` of `build_output.py`, the private import of
`generate.py:569`, and the "put it last" rule. What each target publishes is
the explicit list of section 3.2, not a boolean.

**A user's own output.** Today the answer is a `post_process` hook, crude but
documented. After this split, extensions no longer cover it. Either a target
takes a declared extension point, or this note must state that custom outputs
are out of scope and that such users run their own script on the finished
site - which then requires the core to guarantee that a finished site exists.


## 5. The layout analysis as a product

The report is the distinctive part of this generator: the layout is measured
in a browser and stated as data, so an agent can fix a slide on numbers
instead of guesses. It should be built as a product, not as the output of a
plugin.

- `lib/layout/analysis.py`: pure functions on measured blocks, with the
  checks of `lib/design_checks.py`. No build, no configuration, no `meta`.
- `lib/layout/vocabulary.py`: the registry of checks - code, severity,
  default threshold, description, remedy template. The JSON, the Markdown
  glossary and the documentation are generated from it, so they cannot drift
  (they already have: the README documents `NEAR-ALIGNED` as "3 to 12 px"
  while the code uses `aligned=2, near=12`).
- `lib/layout/report.py`: Markdown and contact sheets, rendered **from** the
  data.
- `lib/layout/measure.py`: the Node runner and the choice of Chrome - the
  configured one, else `PUPPETEER_EXECUTABLE_PATH`, else the one puppeteer
  downloaded, else an installed Chrome, saying which it took. This one is
  done (`plugins/assets/chrome.js`) and only has to move: a measurement must
  not fail because a browser was not downloaded next to the generator.

### 5.1 Findings as first-class objects

A versioned schema is necessary and cheap, but versioning today's content
would version its problems. The substance: a finding must stop being a
heterogeneous row in a kind-specific list - there are 18 record shapes today
and the only field they share is `id`. Every finding carries:

```
{code, severity, finding_id, source: {file, line}, element, measured, limit,
 cause_group, remedy}
```

with the schema version on the document. Three consequences:

- **The JSON is the source of truth and the Markdown is rendered from it.**
  Today it is the other way round: `_problems_by_key()` regex-parses the
  prose of `problem_lines()` to build `changes.md`, so a wording change
  breaks diffing.
- **Severity moves out of the Python tuples** `PROBLEM_KEYS` / `WARNING_KEYS`
  and into the data.
- **Stable identity, designed and not assumed.** Block ids are positional
  (`b.id = i + 1`) and change at every measure - the code says so itself.
  But the obvious replacement does not work either: a file and a line move as
  soon as text is added above, and the same source can appear several times
  in a deck (`occurrence` in `structure.yaml`). Identity has to be built from
  what survives an edit - the page and its occurrence, the kind of finding,
  and a signature of the element - and it has to be tested against real edits
  before anything depends on it. Until then, a per-page diff is safe;
  **persistent suppressions are not**, and they wait.

### 5.2 The source location, which already exists and is thrown away

`lib/source_map.py` writes `data-lhtml-src="<file>:<line>"` on each block.
`plugins/assets/layout_measure.js:558-560` then keeps only the integer: **the
file is discarded**, a nested block falls back to its first marked descendant
with no flag, and text runs - the blocks an author edits most - get nothing
at all (14 of the 108 blocks of the example's first page). So the report says
where a problem is *on screen*, not where it is *in the file*, and the agent
greps by a truncated signature instead. This is the field whose absence costs
most per iteration, and the machinery already exists.

### 5.3 Precision before container

Centralising the vocabulary is worthless without evidence that the checks are
right. The acceptance criterion is a **reference corpus** - a real deck, not
the example site - with expected findings and a stated precision target per
check.

A first run on a deck of 78 slides says what that corpus is for, and what it
is worth. The check reported 109 problems. Grouping the findings per block
brought it to 40, and about 35 of those had one cause: the full-bleed
images, declared `position: fixed` over the whole slide with the class
`overlay`, were measured against the usable area (the inside of the slide
frame) and against the navigation they pass under, although the class was
already honoured for collisions. Two rules settled it - an intentional
overlay is compared with the page, and `RESERVED AREA` counts text only -
and the deck now reports **6 problems**, each one actionable: three texts
covered at 100 % (one of them an image credit), two images displayed at
twice their size, and one block over the usable area that is not declared as
an overlay.

109 to 6 on the same slides, with no check removed: that is the difference
between a report an agent reads and one it learns to ignore, and none of it
was visible on the three pages of the example site.

The same run shows why findings need a cause (section 5.1): 21 `OUT OF AREA`
are one layout repeated over seven slides of a series.

Known defects to settle on the way, beyond the three already fixed:
`WRAPPED` fires on any list item whose second line is under 30 % of the
first, which is a property of ragged-right text rather than a defect; the
density metrics
(`occupancy`, `text_area`, `free_bottom`) are computed against a 1920x1080
window even when `scrolling` is true, which prints statements such as "free
space at the bottom: -6440 px" as facts; and `NEAR-ALIGNED` reports offsets
an author is not allowed to fix, since writing positions by hand is what the
design vocabulary forbids - it must name the design knob or stay silent.

### 5.4 Thresholds: named sets, not free numbers

Three of the eleven checks have options today (`threshold`, `max_words`,
`min_font` in `DEFAULTS`). Six others (`find_wrapped`,
`find_row_misalignments`, `find_fit`, `find_collapsed`,
`find_near_alignments`, `deck_norms`) have constants that `analyse()` cannot
even reach. Making them all free per-project numbers would trade a shared
vocabulary for private dialects: the same slide clean in one project and
broken in another, with nothing saying why. So: **named threshold sets**
(`slides-1920`, `web`, `print`), the effective values echoed in the document
and in each finding as `measured` / `limit`, and the type-scale-dependent
ones (`min_font`) living with the design, which already owns the type scale.

Named sets normalise the **shared** vocabulary; they do not forbid a project
from having rules of its own - and that is not a wish, it already works: a
deck declares its own checks under `design: lint: rules:`, with a pattern and
the advice to print, and the real deck of the corpus uses one. The report
states them as it states the others. What must not happen is the same name
meaning two different things in two projects.

### 5.5 The agent loop is part of the product

The format is optimised today; the loop that consumes it is not, and that is
where the time goes.

- **"Nothing found" and "not looked at" must not read alike.** Half of this
  arrived with `split-agent`: `layout.md` now has a "Report validity"
  section, and `dependencies.freshness()` states `current`, `stale` or
  `unknown` per page, with what changed. What is missing is the other half -
  the counts and the state of the whole deck in one place, so that an agent
  does not conclude that a deck is clean when a third of it is `stale`.
- A machine-readable **verdict** at the top of both files. The freshness is
  prose in the Markdown; the stop criterion still lives in `docs/agents.md`,
  not in the artefact.
- **Findings grouped by cause** and ordered by severity: three `OUT OF AREA`
  from one overflowing column are one problem, and the code already
  half-knows it (it deduplicates `COLLISION` and `HIDDEN TEXT`).
- A **per-page list of what changed** since the last measure, inside
  `layout.md`; `changes.md` is deck-level.
- **Suppression and acknowledgement**, so "warnings understood" can converge
  instead of re-presenting the same items every iteration.
- `layout.md` **readable on its own**: today the first iteration needs
  `agents.md` for the glossary and `structure/design.md` for the remedies,
  and the full block table (108 rows on one example page) is in the way of
  the findings.

### 5.6 Two tiers, stated

Pointed at foreign HTML, the analysis still measures, but the source map, the
design lint and the deck norms are all generator-coupled. That is a
legitimate mode - and the schema must name the two tiers and which fields are
absent in the degraded one, or it will be designed for the weaker one and the
fields that make the report actionable will be optional everywhere.


## 6. Module layout

```
lib/            pipeline: pages, deck, design, rendering, headings, assets, index, structure
lib/layout/     analysis.py, vocabulary.py, report.py, measure.py
lib/targets/    html, pdf: theme, source transforms, deliverables
lib/analyses/   lint, layout: what they need of the build, what they report
plugins/        extensions: pre_include, code_include
themes/         each with its manifest (rendered files, page settings, root, reserved, template)
tools/          outside the build: style_profile (on top of lib/layout), process_video
```


## 7. Scale

Nothing here is urgent at three pages; all of it is cheap to decide now and
expensive to retrofit.

- **The measurement is parallel since `split-agent`**: `jobs` tabs of one
  browser, `auto` being half the processors and at most six. What remains is
  that `tools/style_profile.py` shards the same work its own way, across
  processes: two implementations of one idea, which the extraction into
  `lib/layout/measure.py` should reduce to one.
- **Unbounded process fan-out**: `generate_pdf.py:63` uses a bare
  `ThreadPoolExecutor()`, each task spawning node, Chrome, `pdftoppm` and
  `magick`; `cache_video.py` starts one process per video and codec, all at
  once, with no pool.
- **The deck analysis is whole-deck and in memory**: every page's
  `layout.json` is re-read even under `--only`, and the norms are recomputed
  over a mix of fresh and stale measures.
- **The table of contents is O(all pages), inlined in a script every page
  loads.**
- **Every full build recopies the sources and the theme** into a fresh
  staging directory, with no content hashing.
- **A target for the loop**: edit, `--only --layout`, read. That latency is
  the product claim of section 5, and nothing states a budget for it.


## 8. Breaking changes, stated explicitly

No compatibility shim. Each removal is an error that names the fix:

- `plugin:` listing `menu.py`, `title_submenu.py`, `auto_wrap.py`,
  `redirection_first_page.py` or `cache_video.py`: core stages now; the error
  names the option that replaces the entry (`index:`, `title_id:`, ...).
- `plugin:` listing `layout_report.py` or `generate_pdf.py`: an analysis
  and a target now, selected by `--layout` / `--pdf` or a `preset:` key.
- Any plugin reading an internal key of `meta` that is no longer passed, or
  rewriting a page file outside a declared position.
- Page settings reaching the theme: a theme declares what it receives;
  anything else stays out of the site.
- Error semantics: a core stage raises through the core instead of being
  counted as a plugin failure. Which failures are fatal, and what state the
  site is left in, is part of this contract.
- `structure.yaml` / `structure.json`: an older and more widely read contract
  than `layout.json`, and it has no schema version either.

The configuration is validated against the new model before the build, so the
whole list of what to change is reported at once.

**What it costs an existing project.** For a deck or a course that already
uses the generator, the migration is one configuration file: the `plugin:`
list loses the entries that became core stages, a target replaces the PDF
plugin, and a page setting that the theme used to receive by accident has to
be declared. No source of a slide changes, no theme file changes unless it
is a custom theme, which then gains a manifest. `--check-config` already
validates and prints the resolved configuration without building: it becomes
the migration tool, and it must list every change at once rather than fail on
the first.

This is less brutal than it reads, because a project embeds its own copy of
the generator (`<project>/static_website_lhtml/`, built by its
`generate.sh`). Nothing breaks the day the new version exists: each deck
migrates when its copy is updated, one at a time, and a deck that is not
touched keeps working with the copy it has.


## 9. Walkthroughs to write before the modules are frozen

A decomposition is validated by the journeys it has to support, not by its
diagram. Each of these is written out - configuration, command, files
produced, message expected - and each one that is awkward to write is a
design defect found early:

1. **A minimal project**: the smallest configuration that builds, and what
   appears in the site.
2. **Preview one page while writing it**: `--only` plus `--serve --watch`,
   and what is rebuilt when the page, the theme or the design changes.
3. **Change theme**: what the new theme declares, and what breaks if it
   declares nothing.
4. **HTML and PDF from the same sources**: two targets, one source scan,
   two sets of deliverables, and where each lands.
5. **Check a deck**: run the analyses, read the verdict, fix one slide, see
   only what changed.
6. **Understand a failure**: an extension that raises, a page whose Jinja is
   invalid, a measurement that fails - what the site looks like afterwards
   and what the message says.

## 10. Order of work

Guarantees before structure: what the build promises is decided first,
because it constrains where the components may go. Then the code moves, one
property at a time, never two at once.

0. **Two point fixes first**, because they cost a day of work each time they
   bite and need none of the rest: a measurement finds a Chrome instead of
   failing, an analysis that fails leaves the build alone, and `src`, the
   private settings and the authoring documents stop being published. Done,
   except the authoring documents (`structure/agents.md`, `design.md`,
   `todo.md`), which are still written into the site.
1. **The guarantees of section 3, on paper and under test**: when a partial
   build widens itself, and what a build publishes. These are observable
   from outside, so they can be pinned by tests before any file moves - and
   they are what makes the rest a gain in reliability rather than a
   reorganisation.
2. **The declared positions** of the stages and extensions, and what a
   target may change. The pinning tests of `tests/test_plugin_order.py` are
   rewritten to assert declared positions.
3. **`lib/layout/` as a pure extraction, with no change of behaviour**: the
   same output, byte for byte, from a module that no longer lives in a
   plugin. It depends on nothing else - 996 of the 1271 lines already have no
   tie to the build - and it removes the `sys.path` hacks.
   `tools/style_profile.py` and `tests/test_layout_report.py` are migrated as
   part of this step: both load the plugin by path today.
4. **Then, and only then, the new contracts inside it**: the vocabulary
   registry, the finding schema, the source location, the verdict. Moving the
   code and changing its output in one step would leave nothing to compare
   against.
5. **Targets and analyses**: `layout` and `pdf` out of the plugin list.
6. **The theme manifest**, then the stages that depend on it: `menu`,
   `auto_wrap`, `title_submenu`, `index`, the video cache.
7. **The extension transformation contract** (section 4.2), once the engine
   owns the writes everywhere else.

Expect test churn: 13 of the 18 test files mention plugins. "Each step keeps
the suite green" is the goal, not a free property.


## 11. Open questions

- `--render` and `--lint` are both a stage inside a build and a standalone
  mode. Tools, analyses, or both?
- `lhtml-markup` is an undeclared part of this architecture: `LHTML_OPTIONS`
  includes `wrap-auto`, which overlaps `auto_wrap`, and `CACHE_VIDEO_DIR` is
  duplicated on both sides. Deciding what is core here is partly deciding
  what belongs in LHTML.
- Every stage promoted to core inherits an `--only` variant: which ones can
  be made partial honestly, and which ones always run (section 3.1 says the
  build widens itself rather than guess, but not yet which stages are cheap
  enough to always rerun).
- How far does the limited context of an extension go (section 4.2)? Reading
  a file of the project, as `pre_include` does, is part of its job; reading
  the generated site is not.
