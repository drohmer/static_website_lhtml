# Architecture: core, themes, extensions, targets

Design note for the next major version. It records what the current
structure costs, the rules used to decide where each piece belongs, and the
target they lead to.

Part of it is now built: the point fixes (step 0), the two guarantees under
test (step 1), `lib/layout/` (step 3) and the layout analysis out of the
plugin list (step 4) of the order of work in section 10.
Each section says what it has learned since; section 10 is the current
state and the next step.

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
`generate.py` (`add_layout_plugin`) inserted `layout_report.py` before
`generate_pdf.py` by testing `p.endswith(...)`; a second place tested the
same name again to validate the report output directory; a third was a
function of `lib/configuration.py` dedicated to that one plugin; a fourth
imported two private symbols of it for `--render`. All four are gone with
step 4: the analysis is part of the generator, `--layout` runs it, and the
configuration names no file.

**A plugin performed the publication step.** `plugins/generate_pdf.py`,
`shutil.rmtree(site_dir)`, with `lib/build_output.py` having to know about
it ("PDF-only exports may intentionally remove their staging site"). The
ordering constraint documented in the README ("put `generate_pdf.py` last")
existed only because of this, and nothing checked it. Step 4 needed the
site to survive its post stage, so the export now says what it publishes
(`publish_site`) and the publication step drops the intermediate. The rest
- a target owning its theme, its transforms and its deliverables - is step
7; what is gone is the deletion of a directory under whatever runs next.

**The order of two plugins silently changes the output.** With `pre_include`
then `auto_wrap`, the included text lands inside the document; in the reverse
order it lands before `<!DOCTYPE html>`, outside the document, which puts the
browser in quirks mode. No error, no warning. Pinned by
`tests/test_plugin_order.py`.

**The plugin contract is wide.** The nine plugins touched 16 keys of `meta`
directly, about 20 counting what `lib.structure` and the layout output
validation read on their behalf, and several were internal build state:
`loaded_design`, `measure`, `published_site_directory`, `plugin_paths`,
`config_file`. Two of them are gone (`headings` was written by a plugin and
read by nobody; the layout keys left with the plugin), and the eight that
remain touch 12 keys, of which one is written: `publish_site`, the PDF
export saying what it publishes. The surface shrank with the plugins that
left, not because the contract was narrowed - that is section 4.2.

**The analysis code was trapped inside a plugin** - 1161 of the 1516 lines
of `plugins/layout_report.py` used no `meta` at all - and because it had no
legitimate home, three places reached into it by path: a tool inserted two
entries in `sys.path` and used 12 symbols of it, 4 of them private; the test
file loaded it by location; the core imported it as a package and took two
private names from it. Fixed by step 3: the analysis is `lib/layout/`, and
nothing loads it by path any more; step 4 then removed the plugin itself.
The cost it illustrates stays in this note because the same trap is set for
anything else that ends up in `plugins/` without being an extension.

**Themes depend on plugins, and nothing says so.** All three themes need
`menu.py` (`{{TOC}}` in `themes/*/js/menu.js`); `webpage-frame` also needs
`title_submenu.py`. A default configuration produced an empty summary column
until `title_submenu.py` was added to the default list.

**Three defects found while writing this note, now fixed.** Each one is a
symptom of a missing contract, not bad luck:

- The menu published **every** page setting into `theme/js/menu.js`, a file
  served to every visitor: a `notes:` or `message:` written for the author
  was readable in the site. Fixed with a declared list of keys
  (`plugins/menu.py`), then the same rule applied to what the build writes
  into the site: `structure/structure.{json,yaml}` carries the public part of
  each page, the files the build reads (a page `config.yaml`) are no longer
  copied, and the documents of the project moved out (see 3.2). Missing
  contract, now stated by a list in one place: *which page settings a theme
  may see*.
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

The property is now pinned from outside:
`test_a_partial_build_gives_the_same_site_as_a_full_one` builds the same
sources fully and partially and compares a fingerprint of the whole site,
rather than testing the fingerprints of the dependency system. It fails when
the widening is disabled - checked by disabling it.

What is left:

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

The same applied to the documents the build writes next to them:
`agents.md` (the procedure for an agent), `design.md` (the macros and tokens
of the theme), `credits.md` and `todo.md` were published with the slides
because the build had nowhere else to put them. They are written in
`.structure/`, next to the configuration, beside `.layout/` and
`.verification/`; the site keeps the machine-readable structure the plugins
and `--only` read.

The rule, now applied: **build state lives outside the site; what is
published is an explicit list.** Then `publish:` stops being a boolean. A PDF target
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
- its **content root** and its **reserved areas**, for the measurement. Done
  (`theme.yaml`, `lib/theme.py`): `root`, `exclude`, `width`, `height`;
- its **base template** and the block a page fills, for the wrapping stage.
  Done;
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
when it writes a `<video>`; `plugins/cache_video.py` repeated the same
literal, and now imports it. The plugin does not add content: it changes
what a *core* stage emits, through a side channel neither side declares,
and it must run before LHTML for that reason. It belongs in the core as an
asset stage with a pluggable converter, and the directory name belongs in
the contract. What an undeclared name costs was in the repository: the
example shipped its pre-converted videos under `video_codecs/`, the name
LHTML used before, so 4.6 MB of them were never read and the example never
demonstrated the feature. Nothing could have said so.

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

**What this contract is not.** An interface over strings is a discipline,
not a sandbox: an extension is arbitrary Python and reaches the file system
whenever it wants to. What the contract buys is that an extension no longer
*has* to, that the ones shipped here can be read and tested as functions,
and that a write outside it is a deviation someone can point at - not that
it is impossible.

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

### 4.4 The LHTML boundary, and the document tree

The same argument as 4.2, applied to the markup engine. `lhtml.run(text,
meta)` promises text in, text out. It reads the file system in **four**
places:

- the includes (`read_source`, recursive);
- the video variants (`os.path.isdir` on `assets/cache_video_codecs/`, and
  only when the directory is literally named `assets`);
- the poster of a video (`<name>-poster.jpg`, `export_html.py:131`);
- the **macro files** the pipeline accepts (`pipeline.py:196` resolves them
  against `current_directory`, `macros.py:238` opens them).

An earlier draft of this section counted three and named two callbacks as
the fix; a review counted four. The only read that is not a boundary
problem is `tag_parser.py:30`, which loads LHTML's own grammar.

The generator passes `current_directory = site_directory +
page.site_directory`, so the conversion of the markup depends on the state
of the half-written output directory at the moment of the call.

What that costs is not style. The generator cannot see what LHTML read, so
it **replaces two module functions at run time** (`lib/tracking.py`:
`process.read_source`, `process.process_include_recursive`) to find out, and
the correctness of `--only` - which pages to rebuild - rests on that patch.
The comment admits the cause: "LHTML exposes no source-loader hook yet". If
either function is renamed or inlined, nothing raises; a stale page is
published. The same undeclared split already cost 4.6 MB of pre-converted
videos shipped under the directory name LHTML used before, never read,
nothing said (5.3).

The boundary: **LHTML does not touch the disk.** Not by purism - it has a
CLI and must stay usable alone - but through interfaces the caller
provides, the CLI passing the defaults.

A source loader, and `read(filename) -> text` is too poor for it. It must
give the content, the **canonical identity** of the source (the dependency
store and the provenance of a block both need it: step 6b needed exactly
that, so that a marker carries the file it is written in), the source to
resolve a relative path from, and explicit errors with cycles named first.
A media resolver, covering the poster as well as the variants. And the
macro files, which neither of those two covers.

The conventions of the cache and of transcoding belong to the **asset
handling of the generator**, not to the theme manifest: a theme may change
how a video is presented, but changing the theme must not change the
identity of the cache. An earlier draft of this section said the opposite,
while step 8c had already put them on the right side -
`cache_video_directory:` is a project key and `ASSET_DIRECTORY` lives in
`lib/video_cache.py`.

`wrap-auto` stays, for LHTML used alone; the generator must turn it off
explicitly rather than merely never setting it (small debts).

**And the deeper form of it: a document tree.** `lib/source_scan.py` says
in its own docstring that the lint, the source map, the credits and the
placeholders find LHTML's zones *with LHTML's own regular expressions*, "so
that they agree with it on what is code and what is text". Six consumers of
the generator need LHTML's parse; none can have it, so they rebuild it.
That is `source_scan.py` (159 lines) and `source_map.py` (328), which
injects invisible characters into the text, lets them travel through Jinja
and LHTML, and reads them back out of the HTML - and every rule about where
a marker may sit on a line so that LHTML still reads that line the same way.

**But the tree deletes much less of that than an earlier draft claimed, and
the reason matters.** The lint, the credits, the headings and the wrapping
read the **source**, before Jinja; a tree from `lhtml.parse` is of the text
**after** Jinja. They are two different documents, so `source_scan.py`
survives. And the tree does not recover file and line on its own:
provenance has to be transmitted *through* Jinja - macros, inclusions,
repetitions - which is exactly what the markers do. Measured on the file:

```
source_map.py  328 lines
   ~96  the source side (markers, before Jinja)   -> survive
  ~164  the rendered side (HTML tree, after LHTML) -> deletable
source_scan.py 159 lines                           -> survive
```

So the claim is **~164 lines**, not 486, and only once provenance travels.
What the tree buys is that nothing re-derives the blocks from the produced
HTML - not that the two readings of a page become one.

There is nothing to export today: `pipeline.run` is seven text-to-text
passes over one string (`process_yaml`, `process_include_recursive`,
`process_title`, `process_listing`, `process_bold`, `process_italic`,
`process_tag`), with a `ProtectionStores` of placeholders so the passes can
hide text from each other. The placeholder machinery is the symptom. So a
structured output is not a format to add; it is the core model to replace,
and it should be said plainly before anyone calls it cheap. The shape:
`document = lhtml.parse(source, ...)` and `html = lhtml.render(document,
...)`, with `lhtml.run(...)` kept as the façade. Raw HTML must stay
faithful: LHTML nodes, and **opaque fragments** for HTML, code and
mathematics, with significant whitespace preserved.

**What a probe measured, before committing to it.** The risk was located in
the ~159 lines that decide which `::` is a tag (`process_tag`,
`_dispatch_tag`, `_adjust_bare_tag`, `_is_tag_boundary`): a parser decides
that differently, and that is where the two would disagree. Instrumenting
those functions over three corpora:

| corpus | decisions | rejections |
|---|---|---|
| a deck of 78 pages | 2336 | **0** |
| the example site | 303 | **0** |
| LHTML's own test suite (321 tests) | 736 | **11** |

On content anyone actually wrote, the heuristics never fire. The 11
rejections and 5 extent rewrites are 16 sites in four families:

- **the closing `::` of a valued tag** (`gap::l::`, `box::warn::`): 3 sites.
  This is grammar, not a heuristic - a parser with a state is right by
  construction where the current code uses a lookbehind on `:`;
- **word boundaries** (`a[::2]`, `std::chrono`, `obj.link::`): 6 sites, one
  lexer rule;
- **the extent of a bare `::`** (`::nl.`, `::,`, `::::[...]::`): 5 sites,
  the awkward family - a token whose extent depends on what follows it, to
  be ported case by case against the tests;
- **`::` glued to a placeholder** in highlighted C++: 2 sites, which exist
  only because protection is a text pass leaving sentinels in the stream.
  A tree never descends into a code node, and the family disappears.

So **one axis of the risk is measured**: 16 sites, 2 deleted by the tree, 3
where a parser is better than the status quo, 11 straightforward ports under
existing tests. It is not the whole risk, and the first draft of this
section said "bounded", which was too strong: nesting, the protected zones,
the macros, the closing rules and the line breaks interact, and the probe
touched none of that. A prototype compared against the current engine on
the tests and the corpora is what would bound it (N5).
And the test suite is the specification: 196 of its 246 tests call the public
API and **none** call an internal function, so a change of model that
preserves the HTML leaves them green.

**One consequence to record, because it contradicts the obvious plan.** A
byte-comparison oracle on the real deck was the proposed safety net; the
probe shows the deck would catch none of these - it never triggers one of
them. The net is the 321 tests, the 18 golden files, and adversarial
fixtures to add. The deck oracle stays useful for the rest: titles, lists,
macros, line breaks.

Not measured, and stated as a judgement: the 86 lines of
`process_line_breaks` and its helpers, which guess structure from flat text
(`_is_structure_line`, `_preformatted_depth_change`), should disappear with
a tree.


## 5. The layout analysis as a product

The report is the distinctive part of this generator: the layout is measured
in a browser and stated as data, so an agent can fix a slide on numbers
instead of guesses. It should be built as a product, not as the output of a
plugin.

- `lib/layout/analysis.py`: pure functions on measured blocks, with the
  checks of `lib/design_checks.py`. No build, no configuration, no `meta`.
- `lib/layout/findings.py`: the registry of checks - the key of the check in
  the analysis, its code, its severity, and the sentence it prints. Done.
  Not in it: the thresholds, which are configuration and are validated where
  they are read (`lib/layout_options.py`, `lib/design_checks.validate`), and
  a description per check, which would be a second copy of the README under
  a promise that it cannot drift. One copy that is read is better than two
  that are generated.
- `lib/layout/report.py`: Markdown and contact sheets, rendered **from** the
  data.
- `lib/layout/measure.py`: the Node runner and the choice of Chrome - the
  configured one, else `PUPPETEER_EXECUTABLE_PATH`, else the one puppeteer
  downloaded, else an installed Chrome, saying which it took
  (`plugins/assets/chrome.js`). Done. The Node scripts themselves still sit
  in `plugins/assets/`, with those of the PDF export; they move when the
  targets do.

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
  Done. It used to be the other way round: `_problems_by_key()` regex-parsed
  the prose of `problem_lines()` to build `changes.md`, so a wording change
  read as a problem that appeared. The diff now compares the `code` of a
  finding and the signatures of its `blocks`, and a test changes the wording
  of a finding to check that the diff stays empty.
- **Severity moves out of the Python tuples** `PROBLEM_KEYS` / `WARNING_KEYS`
  and into the data. Done, and the two tuples are gone with the two counting
  functions that read them; `count(analysis, severity)` counts records.
- **Stable identity, designed and not assumed.** Block ids are positional
  (`b.id = i + 1`) and change at every measure - the code says so itself.
  But the obvious replacement does not work either: a file and a line move as
  soon as text is added above, and the same source can appear several times
  in a deck (`occurrence` in `structure.yaml`). Identity has to be built from
  what survives an edit - the page and its occurrence, the kind of finding,
  and a signature of the element - and it has to be tested against real edits
  before anything depends on it. Until then, a per-page diff is safe;
  **persistent suppressions are not**, and they wait. For the same reason
  there is no `schema_version` on the document yet: a version is a promise
  about a shape, and `finding_id` is still missing from this one.

What the record holds: `{key, code, severity, blocks, subject, detail,
text, data}`. `measured` and `limit` are not fields of it. The 26 checks do
not measure the same thing - a collision has an area, a near alignment a
delta and a reference, a wrapped title a number of lines - and giving them
all two numbers would have meant inventing values. `data` is the row the
check produced, with the numbers in the shape that check actually has.

What this deletes: the two severity tuples, two counting functions, a regex
that read codes back out of rendered prose, a second regex that read block
numbers out of it, and 80 lines of `page_markdown` that built four sections
by hand. `report.py` goes from 440 lines to 339 and `analysis.py` from 806
to 791, against 256 for `findings.py`: the whole is 140 lines longer, and
that is the honest price. The sentences were not duplicated before, they
were scattered; what is new is the declaration around each of them. Adding
a check is one builder and one line of `CHECKS`, and nothing else in the
project holds the list.

Checked against the real deck: the problems, the warnings and the
differences with the deck are identical, word for word, on all 78 pages.
The notes changed on purpose - `#1 × #2 overlap (x 15..435, ...)` is now
`INTENTIONAL OVERLAP #1 × #2: x 15..435, ...` - because a note that carries
no code was the one finding the reader could not grep for and the diff
could not key on.

### 5.2 The source location, and what it is worth

`lib/source_map.py` writes `data-lhtml-src="<file>:<line>"` on each block,
and the measurement keeps it whole. What was missing was the use: **the
findings carried none of it**. A report said `HIDDEN TEXT #2 under #3` and
the agent had to find #2 in a table of a hundred rows, then grep for its
signature.

Done: every finding ends with where its blocks are written, and the diff of
two builds keeps comparing findings without their places, so a line that
moves is not a problem that changed.

Writing it meant measuring what an earlier draft had assumed, and the draft
was wrong twice. The file was not discarded. And the fallback it feared - a
block taking the marker of a descendant - happens 0 times in the 554
top-level blocks of the real deck. What is true is sharper, and it is the
reason this section is not finished:

- **The line is not always the line of the block.** The build records
  which case it is (`data-lhtml-near`) and the report writes `near line 11`
  and `~11` in the table rather than sending a reader to another block.
  Then measuring said *which* blocks were in that case, and the answer was
  not the one this section had assumed. Of the 107 top-level blocks of the
  deck marked `near`, **none came from an included file**: 100 were
  `gap::l` and 7 were a raw `<img ...>` line. Both take their marker at the
  **start** of their line - a marker at the end would become part of the
  value of the tag - and the block that follows a marker at the start of a
  line is the block that line writes. The line was exactly right and the
  report called it a landmark. The marker now says which of the two it is,
  and the deck has **0 blocks marked `near`** and no finding that says
  `near line`. What stays `near`, and rightly, is 1081 of the 1660
  sub-blocks: an element inside a marked block takes the marker of the
  block around it.
- **One file per page.** Done, and the premise above was its real test: the
  deck has no `{% include %}` at all, so the defect had to be reproduced on
  a project written for it. It was real - a block of `parts/bloc.j2` was
  reported at line 3 of the page, which holds another block. The marker now
  carries the file it is written in (`\ue000<file>:<line>\ue001`) instead of
  having the page's path stamped on it at the end, and `TrackingLoader`
  marks the templates the page includes as the pages themselves are marked.
  Only the templates under the source directories are marked: the theme's
  base template is not content of the page, and stays unmarked.
- **A bare text run gets nothing.** Not because of KaTeX, as a first
  reading of the deck suggested, but because `apply()` writes an attribute
  on a tag and a text run is not one: 10 of the 108 blocks of the example's
  first page, 8 of the 554 of the deck (which also has one list coming from
  a `code::` block, a zone the source map deliberately never marks). The
  deck's other 74 unmarked blocks are the timer it injects by script, which
  no marker can reach.

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
already honoured for collisions. Two rules settled it: an intentional
overlay is compared with the page, and `RESERVED AREA` counts text only.

**Then a third rule, and the reason the corpus has to be the real one.**
With the deck's own configuration the report stood at **83 problems**, and
75 of them were one element: a timer fixed at the bottom left of every
slide, 21 px below the usable area, stated once per slide. A block
`position: fixed` is positioned against the viewport, not placed in the
content, so the margins the content keeps do not apply to it - the same
argument as the `overlay` class, which it does not need to carry. With that
rule the deck reports **8 problems**: four texts covered at 100 %, two
images displayed at twice their size, one block over a reserved area, one
collision. 109 to 8 on the same slides, with no check removed.

The 75 were invisible for a while because the corpus was measured through a
*copy* of the deck's configuration, rewritten to run from elsewhere: in the
copy, `jsAbs` - a list of URL of the site - had been turned into a
filesystem path, the timer script never loaded, and the slides measured
clean. A reference corpus is the project's own configuration, run in the
project's own directory. A copy measures a different site, and it does it
silently.

Which is itself a finding about the product: if a script a deck depends on
stops loading, nothing says so. The 78 slides degrade quietly, and the only
trace is a layout report that changes by 75 findings for no stated reason.

The same run shows why findings need a cause (section 5.1): 21 `OUT OF AREA`
are one layout repeated over seven slides of a series.

**Fourth rule, same argument, on the warnings.** The problems were down to
8, but the deck still printed **203 warnings**, and 163 of them (80 %) were
on a block laid over the page - the timer, the full-bleed figures. For
`DESIGN` it was 83 out of 83: not one design warning was about content. The
rule is the one already written for `OUT OF AREA`, applied twice more.

`NEAR-ALIGNED` leaves an overlay out on both sides: it is positioned against
the page, not in the grid of the content, so neither is it misaligned with
the content nor the content with it.

For `DESIGN` there was nothing to exempt - there was a default to correct.
The role of a block is guessed from the shape of its content (`.katex` is a
formula, `h1` a title, the rest body text), and those guesses judge the
typography of content. Inside an overlay we stop guessing: the role is
`decorative`, which the vocabulary already defines and already leaves
unchecked. An author who wants a timer judged writes `data-lhtml-role` on
it. No exemption mechanism, no new value: one branch earlier in a chain that
already existed.

The deck goes from **203 warnings to 45**, all on content, with the 8
problems unchanged. The dividing line this settles: a check that compares a
block with the **layout rules of the content** (usable area, grid,
typographic scale) does not apply to an overlay; a check that compares
**pixels with pixels** - collisions, hidden text, `RESERVED AREA` - applies
to everything that is drawn. A timer erased by a full-bleed figure is a real
problem, and it is one of the 8.

Known defects to settle on the way, beyond the three already fixed:
`WRAPPED` fires on any list item whose second line is under 30 % of the
first, which is a property of ragged-right text rather than a defect; the
density metrics
(`occupancy`, `text_area`, `free_bottom`) are computed against a 1920x1080
window even when `scrolling` is true, which prints statements such as "free
space at the bottom: -6440 px" as facts; and `NEAR-ALIGNED` reports offsets
an author is not allowed to fix, since writing positions by hand is what the
design vocabulary forbids - it must name the design knob or stay silent. It
is also the only check seen to be irreproducible: two runs of the same
generator on the same deck disagreed on two of the 78 slides, by one
finding each. Most of that was not the check: the videos of those slides
were measured before they had loaded (see 5.7), so the blocks around them
had the wrong width. With the measurement fixed, one page of the ten that
hold videos still flickers by one finding. A check that flaps between runs
cannot be diffed, which is what `changes.md` is for.

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


### 5.7 A measurement that did not happen must not read as one that did

The report is only worth its measurement, and the measurement was not
deterministic. On a deck of 78 slides, between 9 and 15 of its 21 videos
were measured **without their dimensions**, and which ones changed at every
run. A `<video>` whose metadata has not arrived has no size of its own, so
the browser gives it its default box, 300 px wide: the block holding two
videos was measured 670 px wide instead of 1772, and every geometric check
of that slide - collisions, overflows, alignment, fit - ran on a rectangle
the slide never shows. `render_health` said `ready`.

Two causes, and the deck answered which: a video paused before it has
asked for its data may never fetch it, and `freezeMedia` waited only 10 s
for metadata before giving up silently. Measured on the same deck, six tabs
in parallel, 21 videos:

| asking for the data | budget | measured without dimensions |
|---|---|---|
| no | 10 s | 9 to 15, a different set each run |
| yes | 10 s | 9 to 12 |
| no | 30 s | 10 |
| yes | 30 s | **0** |

Neither alone is enough, and the pair costs nothing: 53 s for the deck
either way, because the wait of one tab overlaps the work of the others.
`jobs: 1` also loses none - at 117 s instead of 53. Two Chrome flags
against background media suspension were tried on the way and changed
nothing; they are not in the code.

Two things follow for the architecture, beyond the number:

- **A measurement that could not be taken is a finding, not a silence.** A
  video without its dimensions is now recorded in `render_health`, with its
  state, and the page says its measure is incomplete. The verdict of 5.5
  has to carry this: "nothing found" and "measured on a box that is not the
  one of the slide" cannot read alike.
- **The fast loop cannot see this class of defect.** `--only` on four pages
  loaded those videos every time; it took the full deck, several times, to
  see it. A check that only appears under the real workload needs the real
  workload, and the reference corpus of 5.3 is where it belongs.

What remains: with the budget raised, one of the ten pages holding videos
still differs by one `NEAR-ALIGNED` between two runs. Known, and small
enough to wait for the finding schema.

## 6. Module layout

```
lib/            pipeline: pages, deck, design, rendering, headings, assets, index, structure
lib/theme.py    what a theme declares about the build (theme.yaml)
lib/layout/     analysis.py, findings.py, report.py, measure.py, build.py
lib/targets/    html, pdf: theme, source transforms, deliverables
lib/analyses/   lint, layout: what they need of the build, what they report
plugins/        extensions: pre_include, code_include
themes/         each with its manifest (rendered files, page settings, root, reserved, template)
```

`lib/layout/` exists, with all of its files, and `lib/theme.py` with the
manifest of section 4.0 (step 8a). `lib/targets/` and `lib/analyses/` do
not exist yet: they are N2 and N4. `tools/` is gone: both scripts it
held were dead code.


## 7. Scale

Nothing here is urgent at three pages; all of it is cheap to decide now and
expensive to retrofit.

- **The measurement is parallel since `split-agent`**: `jobs` tabs of one
  browser, `auto` being half the processors and at most six. The second
  implementation of that idea (a tool sharding the same work across
  processes) is gone with the tool.
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
- `plugin:` listing `layout_report.py`: an analysis now, selected by
  `--layout`, with its options under `layout:` instead of `plugin_arg:
  layout_report:`. Both spellings are refused by name, with the change to
  make (done). `generate_pdf.py` follows at N2, as a target selected by
  `--pdf` or a `preset:` key.
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
validates and prints the resolved configuration without building, and it
must list every change at once rather than fail on the first. There is no
migration tool: this is a major version, and a project migrates by hand,
guided by those errors. The corpus measured what that costs - its five
copies moved to LHTML 3 with a diff of 266 lines (N1).

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
property at a time, never two at once. A third rule earned on the way, and
it reordered the second half of this list: **at equal value, what deletes a
special case comes before what adds a concept.**

**Where this stands, for whoever picks it up.** Steps 0 to 6 and 8 are
done, and the step 2 that was deferred is settled rather than done. The
build runs everything a bundled theme needs as a stage of its own
(`lib/wrap.py`, `lib/headings.py`, `lib/menu.py`, `lib/index_page.py`,
`lib/video_cache.py`); `plugins/` holds `pre_include`, `code_include` and
`generate_pdf`, and the default `plugin:` list is empty. A theme declares
its contract in `theme.yaml` (4.0), a page says what it is in its front
matter, and the layout analysis reports findings of one shape recorded in
`layout.json` (5.1). What remains is **Next** below, reordered by the
measure of four real projects (the corpus, just before it): the corpus under
test first, then what LHTML can delete, a project made of decks and
targets, and the document tree last.

The checks that matter before and after any step: `python3 -m pytest -q`
(about two minutes), `LHTML_BROWSER_TEST=1 python3 -m pytest -q
tests/test_layout_integration.py` for the browser ones, and a build of the
example site compared byte for byte against the previous commit in a git
worktree - which is how 8a, 8b and 8c were each checked.

### Done

0. **Two point fixes**, because they cost a day of work each time they bite
   and need none of the rest: a measurement finds a Chrome instead of
   failing, an analysis that fails leaves the build alone, and `src`, the
   private settings and the authoring documents stop being published - the
   documents of a project now live in `.structure/`.
1. **The guarantees of section 3, under test.** A partial build and a full
   build of the same sources give the same site, pinned on a fingerprint of
   the whole site and checked to fail when the widening is disabled; what a
   build publishes is pinned by the privacy tests of
   `tests/test_build_safety.py`. Observable from outside, so they hold while
   the components move.
3. **`lib/layout/` as a pure extraction.** `plugins/layout_report.py` went
   from 1522 lines to 259 (the hook: which pages to measure, what to keep of
   a previous build, where to write); `analysis.py`, `report.py` and
   `measure.py` hold the rest, and `tests/test_layout_report.py` imports
   them instead of loading a plugin by path.

   What "no change of behaviour" was checked against: the same deck built
   with the generator before and after the move gives the same findings on
   all 78 pages. The check has to name what it ignores, because a rebuild
   changes it on its own - the random name of the staging directory, the
   order in which the browser reports the resources it loaded, and the PNG
   renders. One page did differ, and it differs between two runs of the
   *same* generator as well (a video measured before it had loaded, 5.7): the run
   before the move and a second run after it agree exactly.

   A second check, on a course website of 31 pages written against a copy of
   the generator five months old: same 82 files, same paths, and it builds
   both with the current theme and with its own. The theme contract has not
   moved in practice, which is worth knowing before the theme manifest of 8a rewrites it.
4. **The layout analysis is no longer a plugin.** `--layout` runs
   `lib/layout/build.py` from the core, at the point in the build the plugin
   occupied. Four special cases are gone with it: `add_layout_plugin` and
   its insertion before `generate_pdf.py`, a second test on the same file
   name, the function of `lib/configuration.py` written for that one plugin,
   and the import of two of its private symbols by `--render`. The options
   are the configuration key `layout:`; a configuration of the previous
   version is refused by `--check-config` with the change to make, named.

   It needed one thing from the PDF export: the site had to survive the post
   stage. `generate_pdf` asked for its intermediate HTML not to be published
   instead of deleting the directory, so "put `generate_pdf.py` last" is no
   longer a rule anyone has to know - checked by building the PDF and the
   layout report of the same sources in one run, which produces slides.pdf,
   images/ and the report, and publishes no site.
5. **The source location in the findings** (section 5.2). Every finding
   says where the blocks it names are written, so the agent opens a file at
   a line instead of looking a block number up in a table and grepping for
   its signature - and says `near line 11` where that line is the one of
   what surrounds the block rather than its own, which the build now
   records instead of hiding. What is left of 5.2 is the file: one marker
   carries one path, the page's, so a block from an included file is given
   a line of the page. That needs the marker to carry the identity of the
   file it came from, which is step 6b below.

6. **The contracts inside `lib/layout/`.** The 18 record shapes of the
   checks became one: `lib/layout/findings.py` declares, per check, its
   code, its severity and the sentence it prints, and `findings(analysis)`
   returns the records. Severity is in the data, `PROBLEM_KEYS` and
   `WARNING_KEYS` are gone, the four sections of a page report are rendered
   from the records, and `changes.md` compares codes and block signatures
   instead of regex-parsing prose. `analyse()` records the list in
   `layout.json`, so an agent reads what was found instead of parsing
   Markdown - and a report written from a build read back from disk says
   what *that* build found.

   Checked on the real deck: the problems, the warnings and the differences
   with the deck are identical word for word on all 78 pages; the two notes
   gained a code on purpose (section 5.1).

   Three things named for this step are deliberately not done. `finding_id`:
   stable identity has to be tested against real edits before anything
   depends on it (5.1). The `schema_version`, which would promise a shape
   still missing that field. And the verdict - what the whole report
   concludes - which waits for both, because a verdict nobody can diff is a
   sentence, not a contract.

6b. **One file per page, and the line that was right all along** (5.2).
   The marker carries the file it is written in instead of having the
   page's path stamped on it at the end, and the Jinja loader marks the
   templates a page includes: a block of `parts/bloc.j2` names that file
   and its line, where it used to be given a line of the page holding
   another block.

   Measuring first changed what this step was. The 107 blocks of the deck
   reported `near` did not come from an included file - the deck has no
   `{% include %}` at all. They were `gap::l` and raw `<img>` lines, which
   take their marker at the **start** of their line, and a block that
   follows a marker at the start of a line is on that line. The report was
   calling a right answer a landmark, 100 times. Both cases are now exact,
   and the deck has 0 blocks marked `near`; the included-file defect was
   real but unexercised, and had to be reproduced on a project written for
   it before it could be fixed.

8a. **The theme manifest** (section 4.0). A theme declares in `theme.yaml`
   the template a page is wrapped in, the block it fills, and what the
   measurement takes as the content of a page. Those answers were written in
   the engine and in an extension: `theme/template/base.html` and `content`
   in `plugins/auto_wrap.py`, `root: 'body'` and `exclude: 'nav, footer'`
   among the defaults of `lib/layout_options.py` - the answers of the
   `slides` theme, applied to all three themes shipped here.

   The order is engine, then theme, then project. The project keeps the last
   word because it is the one that knows it added a banner; the engine keeps
   a fallback so that a theme with no manifest builds exactly as before.
   A theme may declare only what describes a theme: `root`, `exclude`,
   `width`, `height`, `reserved`. Thresholds, output directory and jobs are
   a project's business, and a manifest that claims them is refused by name.

   What it was worth, measured on the example site, which uses
   `webpage-frame` and configures no layout: **3 blocks over 3 pages became
   145**. Its whole page was being measured as a single box - the degenerate
   case the build already warned about - because the selector of the theme's
   frame was something every project had to know and write down. The deck,
   which did write it down, is unchanged to the finding.

8b. **The stages that depend on the theme manifest.** First two of them:
   `plugins/menu.py` is `lib/menu.py` and `plugins/title_submenu.py` is
   `lib/headings.py`, run by the build itself. The manifest grew the key
   that made it possible: a theme declares `toc: {file, keys}`, so a theme
   with no menu gets none - which a project could not say, having no way to
   know. `plugin_arg: menu: keys:` is gone with it; the extra page settings
   a menu carries belong to the theme that displays them.

   The default `plugin:` list drops from four entries to two, and the
   example's configuration from three to one. Checked on the example site:
   the build is byte-identical except the manifest itself, which the theme
   copy carries into the site.

8c. **The last three, and the ordering debt settled.** `auto_wrap.py` is
   `lib/wrap.py`, `redirection_first_page.py` is `lib/index_page.py` and
   `cache_video.py` is `lib/video_cache.py`. **The default `plugin:` list is
   empty**, and `plugins/` holds `pre_include`, `code_include` and
   `generate_pdf` - the last of which leaves at N2.

   The index is unconditional rather than a key: a site whose root has no
   `index.html` is broken, and a key nobody sets is not simpler than no key.
   The video cache is the opposite case, and the one decision of this step:
   it needs a transcoder on the machine and minutes of work, so it runs when
   a project says where its cache lives (`cache_video_directory:`) and does
   nothing otherwise. The plugin used to fall back to a default directory
   and print that it had; five projects relied on that fallback, and the
   migration error names the key they must now set.

   **The deferred step 2 is settled rather than done.** `tests/test_plugin_order.py`
   pinned the pair `pre_include` / `auto_wrap`, one of its two tests pinning
   the bad outcome: wrapping first put the included text above
   `{% extends %}`, so it landed before `<!DOCTYPE html>` and the browser
   rendered in quirks mode - "pinned as it is today, not endorsed". The
   wrapping is a stage now and runs after the extensions of the pre stage,
   so that order is not something a configuration can express. A registry of
   declared positions would have ordered the two; removing one of them
   removed the question.

   Two things the move surfaced. A defect: the wrapping put a multi-line deck
   title into `{% set pageTitle %}`, so the second line was printed in the
   tab of the browser - `deck.scaffold` already kept the first line only, and
   the two now agree. And a contract nothing tested: `lib/video_cache.py`
   writes the variants that `lhtml/export_html.py` probes for, through a
   directory name shared by an imported constant and an `assets` convention
   neither side declares (4.4). `tests/test_video_cache.py` pins it from the
   outside, with the variants already in place, so it needs no transcoder.

   The example site is byte-identical to the previous version, built with
   `plugin: []`.

   One more hole closed on the way, left by 6b: the `line` column of the
   block table showed a bare number for a block written in an included
   file, which a reader takes for a line of the page. It writes `file:n`
   there now, the form the findings already used.

   **A project embedding its own copy does not migrate by being rebuilt.**
   The reference deck vendors the generator *and* the themes
   (`<project>/static_website_lhtml/`), so its theme has no manifest and
   its configuration still lists the plugins its own copy still has. Both
   are consistent, and they migrate together when the copy is synced -
   which is the point of section 8's last paragraph, now observed rather
   than predicted.

### Settled without being done: the declared positions (was step 2)

The declared positions of the stages and extensions. Two plugins rewrote
the same file, `pre_include` and `auto_wrap`, and their order was pinned by
`tests/test_plugin_order.py`. The note deferred the registry on the grounds
that machinery built for a pair whose second member is leaving loses its
purpose before it serves - and that is what happened: `auto_wrap` became
`lib/wrap.py` at step 8c, the core wraps after the extensions have written,
and the order that used to break a page is not something a configuration
can express. **Removing one of the two removed the question the registry
would have answered.** If a second extension ever needs ordering against a
first, it is a line of configuration, not a system.

### The corpus: five projects, measured (October 2026)

Five real projects were measured against this note before N1 starts. None of
them runs this generator: each vendors its own copy, of three vintages.

| Project | Sources | Copy of the generator | How it builds |
|---|---|---|---|
| a talk (`soiree_mathematique`) | 197 | 2026-10-10, has `deck`, `--layout` | `configure.yaml` + `deck.yaml`, one deck |
| a course, slides (`epita_ani3d` lecture) | 182 | `ad1490a`, 2026-09-27 | a `generate.py` of the project |
| a course, lab website (`epita_ani3d` lab) | 13 | `ad1490a`, 2026-09-27 | `configure.yaml`, one site |
| a course, slides (`csc_43043`) | 893 | 2026-01, with a copy of LHTML in `lib/lhtml` | `justfile` + three scripts |
| a library documentation (`cgp_documentation`) | 42 | 2026-01, the same | `configure.yaml`, one site, both extensions |

The copy of LHTML in `lib/lhtml` is dead code wherever LHTML is installed:
the generator of that vintage puts it at the *end* of `sys.path`, so the
installed package wins. All five build with LHTML 2.5.1.

The fifth project was added after the first four were measured, and it is
the one that exercises what the others do not: `include::` 4 times (two
HTML schematics, two C++ headers inside `code::`), the `code_include`
extension 19 times (`includeadv::`), and `pre_include` with a file of
macros. Its build runs `git pull` on the repository it documents; the copy
in the corpus has no remote, so its code stays where it was.

What it changes for the steps below:

- **A course is several decks and two targets, and the generator does not
  know it.** Both slide courses wrap the generator in a script of their own
  that loops over the chapters, writes a temporary configuration per chapter
  and per target (`site_directory: _site/<chapter>/html/`, then `pdf/` with
  the `slides-pdf` theme), calls `generate.py` through `os.system`, and moves
  the PDF. `compile_dirs` in those scripts is a hand-written `--only`. One of
  them also generates the section slides from a `PLAN.toml` and a second site
  with time badges from a `schedule.yaml` - what `deck.yaml` does for the
  talk, written a second time. N2 is therefore not "PDF as a target" of one
  site: it is **a project of N decks, each built to the targets it asks for**,
  and the wrapper scripts are the measure of success - they must disappear.
- **Of the four reads of N1, two are barely exercised.** Over 1327 sources:
  `include::` 4 times, all in the documentation, a `-poster.jpg` 0 times;
  videos 266 files, referenced by `videoplay::` (280), `media::` (77) and
  `video::` (48). Since compatibility is not a constraint, `include::`
  (which Jinja already does) and the poster convention are removed from
  LHTML rather than given an interface (N1).
- **`::` is not only LHTML's.** `std::` appears 440 times in the C++ course,
  inside code. The opaque fragments of N5 are not a refinement: on the
  largest corpus, code (`code::`, 802) and mathematics (`\(`, 2452) are where
  a structured parser would be wrong first. That corpus is the one N5 must be
  compared on.
- **The authoring debt is one project's.** The 276 `gap::` of the
  authoring-surface section are all in the talk; the three teaching projects
  have none, nor any `{% set layout %}`. What they write is `div::` (3494 in
  the corpus), `img::` (1486), `code::`: a layout vocabulary that replaces
  nested `div::` is the larger lever.
- **Migration is by hand.** Five copies of three vintages, two of them
  built by scripts. A tool that rewrites them was considered and dropped
  (N3): this is a major version, and the errors of section 8 say what to
  change.

The LHTML of the GitHub repository (`2.5.1`, 321 tests) is identical to the
copy under `codes/lhtml/lhtml`, which is not a git checkout: N1 and N5 start
from a clone (`codes/lhtml/repo`).

### Next

The order of a review of October 2026 put the interfaces of LHTML first.
The corpus above reorders it, on the rule of this section - what deletes a
special case before what adds a concept - and on one it adds: **the
corpus checks the existing uses, targeted tests define the new
behaviours.** What a project of the corpus does must give the same site
after a step; what none of them does yet is defined by a test written
with the change. The steps are N0..N6; the old
numbers of the review are given where they help.

LHTML is a separate repository, `github.com/drohmer/lhtml` (the package
source is under `src/lhtml/`, its tests under `test/`). N1 and N5 are
work in that repository, released before the generator can use them; N1 is
a major version of LHTML, since it removes syntax.

**N0. The corpus under test.** Copies of the sources of the five projects,
outside this repository, each built **with the copy of the generator it
vendors today**, and the result kept as its reference: the files, their
paths, and a fingerprint of the HTML once the names a rebuild changes on
its own are masked (the method of step 3). Two of the five are not built by
a configuration but by a script; the reference is what the script
produces, PDF included. This is the guarantee every later step is checked
against: N2 must give the same sites, N5 the same HTML. It costs no
design, and without it "same site" is a claim about one example of three
pages.

*Done* (2026-10-16). The corpus is `~/static_website_lhtml_corpus`, outside
`~/drives`, which is synced and would upload the built sites (5 GB); the
copies are APFS clones. `build_reference.sh` builds a project with its own
copy, `run_twice.sh` builds it twice and compares, and `tests/corpus.py`
writes and compares the fingerprints. Each project was built twice in a row
and gives the same site: 424, 888, 2876, 8746 and 419 files, the two courses in
75 s and 4 min 30 with their PDFs. What it took, and what it found:

- **A render is not compared byte for byte.** The PDFs and the images of
  the slides (`images/slide_NNN.jpg`) change at every build - the dates and
  the identifier of the PDF, and the frame of a video at the moment of the
  capture (5.7). A PDF is compared on its number of pages and its extracted
  text, an image of a slide on its presence. The HTML needed no mask at all.
- **The PDF target fails silently.** Built in parallel, Chrome missed its
  fixed 4 s on 6 pages, one chapter got no PDF ("Document stream is
  empty"), and the build returned 0. Built alone, a timeout still happens
  (0 to 3 per build) but changes no page. N2 must make a missing deliverable
  an error, and the measurement wait on the page rather than on a clock.
- **The old copies publish build state.** The talk's `structure/structure.json`
  carries absolute paths of the machine - what step 0 made private, seen on
  a copy that predates it.
- **The reference depends on the LHTML installed**, not only on the copy:
  the lab website rebuilt with LHTML 2.5.1 differs from its published site
  by the spacing of a `<video>` tag. A fingerprint records the versions, and
  `compare` says when they differ.

**N1. LHTML reads no file during a build** (the old N1, reversed: a
deletion instead of an interface). LHTML 3.0, since it removes syntax.

What LHTML reads during a build of the generator, measured before deciding:

| Read | Where | Corpus (1285 sources) |
|---|---|---|
| `include::`, in text and inside code blocks | `process_include_recursive`, `find_file`, `read_source` | 0 |
| the poster `<name>-poster.jpg` | `export_html.py:131` | 0 files |
| the video variants of `cache_video_codecs/` | `export_html.py:139-150` | 405 videos |
| the macro files | `macros.py:238` | never: the generator passes the macros as a mapping |

And `lib/tracking.py` patches two functions, both for `include::`. So:

- `include::` is removed, with `find_file`, the include expansion, its cycle
  error and the `directory_include` option. Jinja includes, with a
  provenance the generator records (step 6b).
- the poster convention is removed: a poster is an attribute the source
  writes, not a file LHTML probes for.
- the video variants are a **callback**, `media(src) -> [(url, mime), ...]`,
  that the caller passes; without it LHTML writes the source as given.
  `CACHE_VIDEO_DIR` and the `assets/` convention leave LHTML for
  `lib/video_cache.py`, because **changing the theme must not change the
  identity of the cache**.

The source loader the review asked for has nothing left to load: the text
comes from Jinja, already tracked by `TrackingLoader`, and the macros from
the configuration. `lhtml_includes`, the patch, is deleted; reading a file
remains a detail of LHTML used alone, from its command line, with no
interface. `wrap-auto` and `directory_include` leave `LHTML_OPTIONS`.

Checked by the tests of both repositories and by the corpus (N0), whose HTML
must not change but where `include::` is written.

*Done* (2026-10-16), LHTML 3.0.0 on the branch `v3-no-file-reads` of the
clone, not released. LHTML loses `include::` (refused by name, with the
Jinja way in the message), the poster probe and the variant probe, and
gains `media`; a tag handler receives the context of the run. The generator
gives `lib/video_cache.media(page_directory)` to LHTML, owns
`CACHE_VIDEO_DIR`, and `lhtml_includes` is deleted with the
`include_dependencies` it fed. 320 tests for LHTML, 293 for the generator,
the 12 browser tests; the example site byte-identical to the previous
commit, its transcoded variants included.

The corpus cannot be built by this generator before it is migrated (N2), so it was checked
one level down: every call of `lhtml.run` of the five reference builds is
recorded (914 calls, `record_calls.sh`) and replayed with LHTML 3 and a
`media` that does what LHTML 2 did on its own (`replay_calls.py`). 910 give
the same HTML; the 4 others are the `include::` of the documentation, now
refused. Those four migrate to Jinja: `{% include %}` for the two
schematics, which are under the sources; the two C++ headers are outside
them, in the repository the documentation clones, which is the job of
`code_include` - N4 decides whether that stays an extension or becomes a
Jinja function of the core.

Then the copies of the corpus were migrated by hand, as a project will be:
each vendored generator gives LHTML a `video_sources(page directory)`, the
talk's generator loses its patch of `include::`, the documentation includes
its schematics with Jinja and its headers with `code_include` (which learned
to insert a whole file). 266 lines of diff (`patches/lhtml3.diff` of the
corpus). Built with LHTML 3, the five sites are identical to their
references, PDFs included; built with LHTML 2.5.1, the migrated copies still
are.

The checks were tightened before N2, on a review's findings. The replay no
longer reads a build directory: LHTML 3's `media` answers with the sources
LHTML 2 wrote for each video, read back from the HTML recorded, so the test
of the parser stands on its own; a call that raised and now converts fails
it. `check_lhtml3.sh` fails when a build fails. A PDF is also compared page
by page on a low-resolution render, which sees a missing image or a moved
block where its text does not; the pages that show a video change with the
frame captured, and a second build of the same sources marks them volatile.

**N1b. LHTML 3 loses what nobody writes**, before 3.0 is released: one
major version, not two. A survey of the 1333 sources of the corpus counted
each construct; what has no use goes, and the replay of the 914 calls says
that no HTML changed:

- mathematics: `\(..\)` (4297 uses) and `\[..\]` (6) stay; `$$..$$`,
  `$..$` and the one-character `$x$` rule (0) go - the most ambiguous rule
  of the lexer, before N5;
- closing a tag: the bare `::` stays; `::name[-]` and `::[-]` (0) go, with
  the tracking of the names of open tags that only they need (`csc_43043`
  writes `span::[-]` twice, read as a style `-`: a latent bug of the
  source, which the removal turns into an error);
- `::#` comments, `verbatim::[]`, runs of `:::` (0): Jinja comments and
  `code::` cover them;
- the YAML front matter of a document (0): the generator strips it before
  LHTML anyway; LHTML receives its options from its caller only, as N1 made
  it receive its files;
- named tags inside inline code (3 `link::`, all in cgp): inline code
  becomes literal;
- the unused fields of a macro (`style`, `variant: true` - a variant is a
  list -, the rendering through `img`/`video`/`link`) and the exports that no caller uses
  (`insert_in_text`, the `process_*` functions, `analyse_tag`,
  `read_yaml`, dead constants of `patterns.py`): the public API is `run`.

Kept although unused: `#id`, chained classes, `{attr}` outside a video - a
regular grammar is simpler than one cut to the uses. So are `video::` and
`videoplay::`, although the 48 `video::` of the corpus all write
`{autoplay muted loop controls}`, `videoplay::` and its `{controls}`:
`video::` is the bare element (a video one starts oneself), `videoplay::` a
preset, and both go through the `media` resolver, which a video written in
HTML or by a macro would lose. Decided: both stay, and `videoplay::`
gains `playsinline` (on an iPhone, an autoplaying video otherwise opens
full screen).

*Done* (2026-10-17), on the branch `v3-no-file-reads` of LHTML. Replayed
on the 914 calls of the corpus, the only changes were the 14 calls of the
documentation that wrote `link::` inside inline code, migrated in its copy
to `<code class="code-inline">link::...</code>`; with them, every call
gives the same HTML, `playsinline` set aside. The five projects built with
LHTML 3 (before `playsinline`) are identical to their references, their
PDFs compared page by page on the render: 22 and 74 pages of the two
courses show a video and are skipped, found by four more builds each - a
video page can show the same frame several times, so the list grows until
a build finds none new.

On the side of the generator, the same survey finds
`include_head` (declared and documented, read nowhere), `title`/`css`/`js`/
`line-breaks` in `LHTML_OPTIONS` (no effect on a page the theme wraps), the
configuration keys `level_print`, `use_tidy`, `title_id`,
`public_page_keys` (0 uses; `chrome` moves to the PDF target), the `layout`
page setting next to `{% set layout %}` (0 against 78), and the aliases of
old names (`plugin_post`, `configure_default.yaml`, `theme_templates`):
one error per removed form, no alias. And three bugs: `expandable-toc`
(cgp) is missing from `DISPLAY_KEYS`, csc's script passes a `--light` that
does not exist, and the refusal of the old plugins misses `auto-wrap.py`.

**W. Windows** (before N2, which rewrites the output paths). Measured on a
Windows 11 machine, Python 3.14: LHTML passes its 320 tests once its CLI
writes `\n` (`newline=''`) and reads its grammar as UTF-8. The generator
fails 50 of 292, for five causes:

- **paths as identifiers**: `os.path.join`/`relpath` (62 calls) build the
  names of pages, deck pointers and URLs with `\`; a deck says
  `ext:c\02_v` where it wrote `ext:c/02_v`. A page, a pointer and a URL are
  POSIX paths (`PurePosixPath`, `as_posix()`); `os.path` is for the disk
  only. Most of the failures;
- **encodings**: four reads or writes without `encoding='utf-8'`, and an
  output to a console in cp1252/cp437 that cannot print every character;
- **the build lock**: `fcntl` does not exist; `msvcrt.locking` raises
  `PermissionError` where the code catches `BlockingIOError`;
- **replacing the site**: `rename` onto an existing directory, or a
  directory a process still holds open, fails where POSIX succeeds;
- **symbolic links** need a privilege on Windows: the tests that create one
  skip without it, and the build copies when it cannot link.

Plus the details of the platform: the first `python` of the `PATH` there is
Inkscape's (`py -3.14` is the reliable launcher), and Chrome is found by its
install path. Done when both suites pass there and a project of the corpus
builds the same site on both systems - a script that runs the suites over
SSH keeps it so.

*Done* (2026-10-16). Both suites pass on Windows (LHTML 294, the generator
289, 16 skipped: Chrome and Node.js are not installed there), and the
example site built there is identical to the one built on macOS (304
files). What it took:

- the names of the pages are POSIX paths from the walk of the sources
  (`filesystem.find_files_in_hierarchy`), and so are the URLs of the video
  variants (`video_cache.media`) and the directories of the configuration
  (`source_directory`, `config_directory`, ... end with `/`, written with
  `/`: Windows reads them);
- a path in a message or a report goes through `filesystem.shown`: relative
  when it can be, with `/`;
- every text file is written with `newline='\n'`: the only differences
  between the two sites were CRLF;
- the build lock locks a byte far from the pid it writes (on Windows a
  locked byte cannot be written, even by its owner);
- a link to a directory is recreated as one (`target_is_directory`), and
  removed with `rmdir`;
- the tests: UTF-8 given where they read or write non-ASCII text, links to
  directories created as such and with native separators, Node.js tests
  skipped without Node.js, the executable bit not tested where there is
  none, and one Chrome test that lacked the `LHTML_BROWSER_TEST` gate.

`tests/windows.sh <ssh host>` copies both checkouts there and runs the two
suites.

**C. What the two commands print.** Today the generator prints a banner,
six stages with `[OK] 0.0s` whatever they did, paths cut at 80 columns
(the console of `rich` in a pipe), and no conclusion: neither the number
of pages, of warnings and errors, nor where the site is. LHTML locates a
problem by a character offset (`Position 5`), and as a library it reports
through Python's `warnings`, which name its own line
(`pipeline.py:218`), not the author's. The rules:

- a problem is one line `file:line:col: level: message`, the line of the
  **source**, not of the HTML Jinja produced - the markers of the source
  map already exist and become always on for the messages;
- the build ends with one line: pages built, warnings, errors, time, and
  the path of the site; the stages print only with `-v`;
- a path is never cut; colour only on a terminal;
- the exit code says whether there was an error; `--strict` makes a
  warning one;
- LHTML returns its diagnostics with their positions (line, column), and
  its CLI prints them in that same format; `--wrapAuto`/`inputFiles`
  become `--wrap`/`input`.

*Done* (2026-10-17). LHTML: `LHTMLWarning` and `LHTMLError` carry `line`
and `column` in the text given to `run`. The protected zones keep the text
they hide, so a place in the prepared text is a place in the source; the
passes before the tags add lines (a heading, a list) but no `::`, so the
k-th `::` the tag pass reads is the k-th of the prepared text, whose place
is computed once. An unknown language of a code block is reported where the
block starts. Generator: `lib/logger.py` is `info`, `detail` (-v), `debug`
(-d), `warning`/`error` with a place; `level_print` is refused. The line
LHTML or Jinja names is in the page as Jinja wrote it: in a build for
development its marker names the source; otherwise the lines of the page
are aligned with its source (`difflib`, the blank and bare `::` lines
anchoring nothing), and a line Jinja wrote names the page alone. Each build
ends with `<pages> page(s) built in <time>[, <n> warning(s)] -> <site or
PDF>`; `--strict` fails a build with a warning. A path in a message is
relative to the current directory when inside it, absolute otherwise, and
the console never wraps.

**M. A page in Markdown.** Possible, and cheaper than it sounds, if the
generator stops reading LHTML where it only needs the HTML: the headings
(`lib/headings.py` reads the `=` lines of the source), the assets of a page
(`source_scan` reads `img::`), the source map and the lint. Once those read
the HTML a page produces, its markup is a converter the author names by
the extension of the file - `index.md.j2` through Markdown, `index.html.j2`
through LHTML - and nothing else: the generator never guesses it from the
content. Jinja runs first either way, so the themes, the macros of Jinja (`{{ box() }}`), the
decks and the targets do not change. Two traps: CommonMark reads `\(` as
an escaped `(` and `_` as emphasis, so the mathematics needs a plugin that
protects it (`markdown-it-py` with `dollarmath`/`texmath`); and the macros
of the design (`gap::`) are LHTML's - a Markdown page uses those of Jinja.
It also settles the boundary of 4.4: what the generator asks of a markup
(text in, HTML and diagnostics out) is a contract with two implementations,
which N5 and N6 must keep.

*Done* (2026-10-17). `lib/pages.py` names the markup by the suffix
(`SUFFIXES`: `.html.j2`, `.md.j2`, both giving `.html`), and `Page.markup`
travels to the scanners (`source_scan.Scan(text, markup)`: a fenced block
is the code zone of Markdown), the headings (`# Title {: #id}` - `{#id}` is
a Jinja comment), the title, the credits (`![a](file)`), the deck (scaffold
writes `# Title` in a `.md.j2`). Less than planned had to move: the stages
did not need the HTML of the page, they needed to know the markup of the
source they read. The theme wraps a Markdown page as an LHTML one, its
content inside the Jinja filter `markdown_page` (lib/markdown_page.py,
markdown-it-py): Jinja converts the content alone, never the HTML of the
theme, and LHTML does not read the page. The mathematics is kept from
Markdown (outside code); a fenced block is highlighted by the function of
LHTML, so the theme styles both alike. Not for Markdown: the macros of the
design, `video::`, the line breaks, the lint, the source-map markers (a
Jinja error is still placed at its line, by the alignment of step C).

The order: N1b with LHTML 3.0, W before N2, C with N2 (which rewrites the
command anyway), M after N2 and before N4 - the contract of a markup and
that of an extension are written together.

**N2. A project is decks, each built to targets** (absorbs the old N2,
"PDF as a target"). The two slide courses say what the generator lacks:
both loop over chapters in a script of their own, and build each chapter
twice - `_site/<chapter>/html/` with the `slides` theme, `_site/<chapter>/pdf/`
with `slides-pdf` - through a temporary configuration and `os.system`.

- A **deck** is a list of pages under one name: a directory of `src/` by
  default (one per chapter), or an entry of `deck.yaml` as the talk does
  today. A project of one site is a project of one deck.
- A **target** is a theme, its source transforms and its deliverables:
  `html` and `pdf` to start with. A project names the targets it builds,
  and the output path is `<site>/<deck>/<target>/` unless the project has
  one deck and one target.
- `--only` names decks as well as pages: `compile_dirs` and `-s <section>`
  of the scripts are this.
- The section slides generated from `PLAN.toml` are a deck structure, the
  one `deck.yaml` already describes: one format, not two. The second site
  with time badges from `schedule.yaml` stays a script until a second
  project asks for it.

`generate_pdf.py` leaves `plugins/` (what remained of the publication
contract: the explicit list of section 3.2 and the `if staging.is_dir()` of
`build_output.py`). Done when the scripts of the two courses are deleted and
N0 gives the same files under the new paths.

*Done* (2026-10-17), in two parts. First the paths: the directories of a
build are `Path`s (`source_directory`, `site_directory`, `theme`,
`config_directory`, ... and the roots of the sources of a deck), joined with
`/` instead of strings ending with `/` joined with `+` at some thirty places;
the place of a page in the site stays the string the theme reads
(`page_path(entry)`). Then the project, decided with the author:

```yaml
decks: directories          # each directory of the sources is a deck
targets:
  html: {theme: slides}
  pdf: {theme: slides-pdf}  # its theme.yaml says export: pdf
```

- `lib/project.py` plans the builds, deck by deck and target by target, each
  the build of a site with its own directories and theme: `<site>/<deck>/
  <target>/`, the videos in `<cache>/<deck>/`. Without `decks`, the project
  is one deck; without `targets`, one target built into the site itself.
- All the targets are built by default; `--target html` chooses.
  `--only 01_procedural` names a deck, `--only 01_procedural/03_noise`
  pages of it.
- The PDF is a target: a theme declares `export: pdf` (`lib/theme.py`), and
  `lib/pdf_export.py` (the former plugin) renders the site to
  `<site>/<deck>/<deck>.pdf` and `images/`, after the menu is written; the
  site is not published. `generate_pdf.py` in `plugin:` is refused, naming
  the target.
- The builds run one after the other; one that fails does not stop the
  next, and the command fails, naming it - where a script that called
  `os.system` went on and returned 0.

Measured on the corpus: the two courses built by one command each, and by
what their scripts did with this generator (each chapter, each theme, a
temporary configuration, the PDF renamed: `as_the_script.py` of the
corpus), give the same files - 2876 and 8746 minus the `slides.pdf` copies
csc kept - and the same PDF text, except the pages that show a video (the
frame captured) and, once, the time shown by a video player. The scripts
are gone from the projects that migrate; `generate_sections.py` (the
section slides of `PLAN.toml`) still writes sources, and the site with time
badges of `schedule.yaml` stays a script, as decided above.

Two findings on the way. The transcoding of the videos needs `ffpb`, and a
cache made by an older generator lacks the variants the current one makes:
building the corpus with its videos transcodes for hours, so the comparison
ran without `cache_video_directory`. And `video_convert` joined the
command into a string for the log, which a `Path` broke: no test ran the
transcoding, one does now.

*Verified* (2026-10-17) by four independent reviews (LHTML, the core,
the layout code and N2, and an end-to-end run with Chrome). What they
found is fixed, each with a test:

- a project of several builds shared its state: `.verification/` (so
  `--only` rebuilt everything), `.layout/` and the credits of
  `.structure/` were overwritten by the last build. Each build keeps them
  under `<deck>/<target>/` now (`Build.scope`);
- the PDF export: the images of a deck without targets went to a shared
  `images/`, old slide images stayed, a site kept by `--debug` stayed
  published and stale - each fixed, and `images` is not a target name;
- `--check-config` printed no valid YAML with several builds, `--render`
  and `--lint` ran once per build, an error of one build (a missing
  plugin) stopped the others, `--watch` ignored the themes of the
  targets, a theme of the generator could be named only in `targets`, and
  `decks: directories` without a deck built nothing silently;
- regressions of the redesign: `line-breaks:` no longer reached LHTML
  (it is a configuration key again), malformed front matter was ignored
  silently (it fails the page, naming it), a front matter after a BOM or
  in a build for development (marked by the source map) was shown as text,
  and an LHTML error named the staging file instead of the source;
- LHTML: `::#` or `verbatim::[]` inside an attribute group was refused
  (it is text, as in 2.5.1), and the groups of an element with a stray
  closing bracket were no longer kept from formatting.

Left for step C, and done there: the console of `rich` cut a long path in
two (seen on Windows, where the temporary paths are long).

**N3. The migration tool** - *dropped* (2026-10-16). LHTML 3 and the
generator after N2 are major versions; a project migrates by hand, with
the errors of section 8. The corpus copies are migrated that way at N2,
which also gives N5 a corpus built by the current generator rather than by
four old ones.

**N4. The extension transformation contract** (the old N3, section 4.2),
once the engine owns the writes everywhere else. Two extensions remain to
cover, `pre_include` and `code_include`. State what the contract is not: an
interface over strings is a discipline, not a sandbox - arbitrary Python
still reaches the file system.

*Done* (2026-10-17). `lib/extensions.py`: `prepare(context)` once per
build, then `pre_process`, `mid_process`, `post_process(text, context) ->
text` for each page generated; the build reads and writes the files.
`context` is `options` (`plugin_arg`), `config_directory`, `page` (a copy of
its entry) and `warning(message)`, placed at the page. An exception fails
the page, named with the extension, and not the others. A hook of version 2
(`pre_process(meta)`) is refused by its number of arguments, with the form
to write. `pre_include` reads its files in `prepare`; `code_include` clones
or updates its repositories in `prepare`, and learned what the copy of
cgp_documentation does (a `filepath` alone inserts the whole file), so the
corpus builds with the plugin of the generator. `post_process` became a
transformation of the page too: the site-wide writes of version 2 (menu,
redirection, PDF) are stages of the build since N1-N2, and no project of the
corpus had one of its own.

*The corpus migrated* (2026-10-17). The five copies are built by this
generator from a `configure.yaml` each - no build script, no vendored
generator - with the themes they were built with (`themes/`, a `theme.yaml`
added), so that `compare.sh` measures the generator rather than the
evolution of the themes. Against the references built by their own old
generators, every difference has a reason, listed in the README of the
corpus: files no longer published (`config.yaml`, hidden files, the build
documents, settings the theme does not display), files added (per-page
heading summaries, the theme manifest, `design.css`), the heading ids of
`main` where two projects were built by another branch, titles keeping
their punctuation, `playsinline`, and 14 pages of csc six directories deep
that the old generator never built. The comparison found and fixed four
defects of the generator: `expandable-toc` dropped from the menu (cgp), a
build failing without `ffpb` (a warning now, the video shown as written),
the PDF export losing a page to Chrome's timeout under load (fewer Chromes,
a page tried again), and transcoded variants given to a PDF target, whose
pages show one frame (Chrome missed its timeout on a vp9 page).

**N5. A prototype of the structured parser** (the old N4), compared with
the current engine on the tests and on the corpus - `csc_43043` first, the
largest and the one where it would be wrong first: 802 `code::`, 2452
`\(`, and 440 `std::` that are C++, not LHTML. The shape:

```
document = lhtml.parse(source, ...)
html     = lhtml.render(document, ...)
```

with `lhtml.run(...)` kept as the façade. Raw HTML must stay faithful:
LHTML nodes, and **opaque fragments** for HTML, code and mathematics, with
significant whitespace preserved.

**The shape of the tree, validated (2026-10-17)** - with the two choices it
left open: a crossing is closed at the end of its container with a warning
(not an error), and a tag declares itself as `Tag(container, render)`, the
handlers of 3.0 not kept. Measured
first, on the 914 recorded calls of the corpus (the text LHTML receives,
after Jinja):

| | count |
|---|---|
| elements opened by a `::` tag | 3162 |
| ... closed in another container than their own (a heading line, a list item, a bold or italic span) | **2** |
| ... never closed (warned today) | 18 |
| heading lines / list lines / bold spans | 1251 / 4568 / 1206 |
| code blocks / inline code / mathematics | 982 / 819 / 2853 |
| raw HTML tags | 46370 |
| `std::` and other unknown names before `::` (text) | 488 + |

The passes let an element cross a heading, a list item or a bold span,
because each pass writes HTML into the text the next one reads; a tree
nests. Content written by hand almost never crosses: the two crossings are
one line of csc written twice, a `span::[-]` that LHTML 3 reads as a style
(and warns about). So the tree can nest, and the question is only what to
do with a crossing.

```
Document(children, problems)                 problems: warnings with their place
Text(value)                                  as written, newlines included (no <p>)
Heading(level, attributes, children)         = Title, =(.c #id) Title
List(items)                                  * / ** / ***: ListItem(children, sublist)
Strong(children), Emphasis(children)         **...**, __...__ (one line)
Element(name, groups, value, children, closed)
    name      the tag: div, img, link, a macro...
    groups    the bracket groups as written: style [..], classes and id (..), attributes {..}
    value     the word glued after the groups (a URL, a variant: img::a.png, gap::l)
    children  for a container (div::, span::, a macro with a class); a link's
              label [..] is its children, read as text
    closed    'tag' (closed by ::), 'inline' (div::text::), 'void' (img::), 'never'
Code(language, body)                         code::[lang] ... code::[-]   opaque
InlineCode(text)                             `...`                        opaque
Math(text, display)                          \(..\), \[..\]               opaque
Raw(kind, text)                              an HTML tag, comment, <script>/<style>,
                                             a Jinja zone                 opaque
```

Every node carries its `span` (start and end offsets in the text given to
`parse`): line and column are exact by construction, and no longer depend
on the passes adding no `::` (step C). The opaque nodes are the kinds of
the protected zones kept apart on purpose (C, R, I, and math): the tree
never descends into them, which deletes the family of `::` glued to a
placeholder (4.4). URLs and attribute groups are no longer zones: they are
fields of an Element.

Raw HTML stays a leaf: a raw `<div>` and its `</div>` are two Raw nodes,
not a pair. LHTML never matched HTML tags and must not start: the theme
wraps the page in 46370 of them, often open in one template and closed in
another.

```python
document = lhtml.parse(text, tags=None, macros=None)   # no file read, no rendering
html     = lhtml.render(document, media=None, line_breaks=False)
lhtml.run(text, meta, tags)                            # parse + render, as today
```

`parse` needs to know the tags, because an unknown name followed by `::`
is text (`std::vector`) and because a container waits for its `::` where a
void element does not. Today the handler decides that while rendering, by
pushing onto `tag_to_close`; a parser must know it before. So a tag
declares it:

```python
lhtml.TAGS['alert'] = lhtml.Tag(container=True,
                                render=lambda element, children, context: ...)
```

`render` receives the element and the HTML of its children, and returns
the HTML of the element (opening and closing tags included). The handlers
of 3.0 (`(element, tag_to_close, context) -> (html, is_real_tag)`) are
not kept: LHTML 3 is unreleased, and no project of the corpus writes one
(the generator's tags are macros, declared in YAML, whose kind is known).

The line breaks (`line-breaks`, unused in the corpus) become a rule of the
renderer over the tree: a newline in a Text between inline nodes gets a
`<br>`; next to a block node (Heading, List, Code, a block Element, a block
Raw) it does not. The 86 lines guessing structure from flat text go.

**What changes in the output: only a crossing.** An element whose `::` is
in another container than its opening is closed at the end of its own
container, with a warning at its opening and at the `::` that no longer
closes it (today: the HTML is malformed, `<li><span>...</li>...</span>`).
Everything else must be identical, byte for byte.

**How the prototype is checked, before anything uses it:** `lhtml.run`
through the tree against the current engine on the 304 tests, the 914
corpus calls and the fuzzer of the review of step C (60 000 documents
mixing every construct): identical HTML but for the crossings, and the
same problems at the same places. The current engine stays the façade until
then; the tree replaces it in one commit once the three are identical.

What the tree does not do (4.4 still holds): it is the document after
Jinja, so it names no file of the project and no line of a template; the
generator keeps reading its sources before Jinja (`source_scan`) and
carrying provenance through Jinja (the source map). It deletes the rendered
side of the source map (N6), not the source side.

**N6. The consumers migrated to the tree, one at a time** (the old N5).

Three expectations of this note were corrected by the review, and 4.4
carries them: the tree does not recover file and line on its own, the lint
and the parse do not read the same document, and the ambiguity count of the
probe measures one axis of the risk rather than bounding it.

Expect test churn: 15 of the 23 test files mention plugins. "Each step keeps
the suite green" is the goal, not a free property.

### The authoring surface

A page says what it is in its **front matter**, the YAML at its top, which
LHTML has read and removed all along (`process_yaml`) and the build had
never read. Before it, a page setting was a Jinja statement in the page
({% set layout = 'stack' %}, 78 of the 154 slides of the reference deck) or
a `config.yaml` next to it - a file per directory, for a setting of one
page. The front matter joins the chain where it belongs: the directory,
then the page, then the deck entry, which arranges the talk and keeps the
last word.

The Jinja form still works, and the lint does not flag it: a
`{% set layout %}` picks a layout *of* the design vocabulary - it is a
style, not a defect, and 78 findings on a deck would be noise rather than
help. What the documentation now teaches is the front matter.

Still open on this surface, and larger: **276 `gap::` over 94 of those 154
slides**, two per slide that has one. That is vertical spacing written by
hand, which is what section 5.3 says the design vocabulary exists to
forbid - respected to the letter by giving the spacing a token name, and
broken in substance. The fix is not to remove `gap::` but to make it rare:
a layout spaces its parts. The measure of success is hard and already
available - that count must collapse.

### Small debts, cheap, not worth a step of their own

- `meta['headings']` is written by `plugins/title_submenu.py` and read by
  nobody: drop it, with its entry in `RUNTIME_KEYS`.
- `only_pages()` decides the list of pages a second time (section 3.1).

Done: `meta['headings']` is gone with its runtime key; the decision whether
a build may stay partial is `BuildStore.partial_impossible()`, called from
`expand()`, and `only_pages()` only resolves the pointers; the name of the
codec cache is read from LHTML instead of being repeated, and the example's
pre-converted videos - 4.6 MB that nothing read, under the directory name
LHTML used before - are where LHTML looks for them, so the example now
demonstrates the feature it shipped the files for.

An audit of these commits found three defects in them, now fixed and under
test: `--check-config` refused a project that neither asks for the layout
analysis nor configures it, over where its report would have gone (and
`--clean --layout` with it); a plugin that failed during the post stage
suppressed the report, which the plugin order used to make impossible and
which is when the report is worth reading; and the structure of a previous
build was read with the locale encoding instead of UTF-8, which turned a
partial build into a silent full one on a machine that is not UTF-8.

Of the three checks known to be wrong (section 5.3), the one that was a
plain bug is fixed: the density metrics of a scrolling page are measured
over the content that exists, and the space left under the last block -
which a page that continues does not have - is no longer stated as a
negative number of pixels. The other two are not small: `WRAPPED` and
`NEAR-ALIGNED` need a decision about what the check means, and the corpus
to check it against. They stay in section 5.3.

Open, each one or two lines of work:

- `wrap-auto` is still in `LHTML_OPTIONS` of `generate.py`, so a project
  can turn it on and have its page wrapped twice, by LHTML and by
  `lib/wrap.py`. Drop it from the list: the option stays for LHTML used
  alone (4.4), and the generator refuses to forward it.
- `theme.yaml` is copied into the published site, as `design.yaml` already
  is. It is a contract with the build, not content: section 3.2 says build
  state lives outside the site.
- The reference deck vendors the generator and the themes, so it migrates
  only when that copy is synced; until then its configuration is right for
  the copy it runs, and wrong for this one.


## 11. Open questions

- `--render` and `--lint` are both a stage inside a build and a standalone
  mode. Tools, analyses, or both?
- `lhtml-markup` is an undeclared part of this architecture: `LHTML_OPTIONS`
  includes `wrap-auto`, which overlaps `auto_wrap`, and `CACHE_VIDEO_DIR` is
  duplicated on both sides. Deciding what is core here is partly deciding
  what belongs in LHTML. Section 4.4 states the boundary and measures what
  the document tree would cost; what is still open is **when** it is done,
  since it is larger than any step of section 10.
- Every stage promoted to core inherits an `--only` variant: which ones can
  be made partial honestly, and which ones always run (section 3.1 says the
  build widens itself rather than guess, but not yet which stages are cheap
  enough to always rerun).
- How far does the limited context of an extension go (section 4.2)? Reading
  a file of the project, as `pre_include` does, is part of its job; reading
  the generated site is not.
- A script a project injects into every page (`keywords: jsAbs`) is a URL of
  the site, and nothing checks that it resolves. When it stops resolving,
  every page degrades silently (section 5.3). Is that a build check, a
  layout finding, or part of the theme's injection-point contract (section
  4.0)? It is cheap as a build check and belongs to the contract.
- ~~`position: fixed` and the other checks.~~ Settled (section 5.3): a check
  against the layout rules of the content (`OUT OF AREA`, `NEAR-ALIGNED`,
  the design roles) does not apply to an overlay; a check of pixels against
  pixels (collisions, hidden text, `RESERVED AREA`) applies to everything
  drawn.
