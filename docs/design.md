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
lib/layout/     analysis.py, findings.py, report.py, measure.py, build.py
lib/targets/    html, pdf: theme, source transforms, deliverables
lib/analyses/   lint, layout: what they need of the build, what they report
plugins/        extensions: pre_include, code_include
themes/         each with its manifest (rendered files, page settings, root, reserved, template)
```

`lib/layout/` exists, with all of its files. `tools/` is gone: both scripts
it held were dead code.


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
  make (done). `generate_pdf.py` follows at step 7, as a target selected by
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
property at a time, never two at once. A third rule earned on the way, and
it reordered the second half of this list: **at equal value, what deletes a
special case comes before what adds a concept.**

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
   moved in practice, which is worth knowing before step 8 rewrites it.
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

### Deferred, with a reason: the declared positions (was step 2)

The declared positions of the stages and extensions, and what a target may
change. Two plugins rewrite the same file today, `pre_include` and
`auto_wrap`, and their order is already pinned by
`tests/test_plugin_order.py`. One of the two becomes a core stage at step 8.
A position registry built for a pair whose second member is leaving is
machinery that loses its purpose before it serves. The positions are
declared at step 8, when the theme manifest has emptied `plugins/` down to
the two real extensions - where ordering two declared extensions is a line
of configuration, not a system.

### Next

7. **PDF as a target**: its own theme, its own source transforms, its own
   deliverables, and publication by the explicit list of section 3.2
   instead of `shutil.rmtree(site_dir)`. Deletes the "put `generate_pdf.py`
   last" rule and the `if staging.is_dir()` of `build_output.py`. Separate
   from step 4 because it carries the publication contract, which step 4
   does not touch.
8. **The theme manifest**, then the stages that depend on it: `menu`,
   `auto_wrap`, `title_submenu`, `index`, the video cache - and the declared
   positions of the two extensions that remain.
9. **The extension transformation contract** (section 4.2), once the engine
   owns the writes everywhere else.

Expect test churn: 14 of the 22 test files mention plugins. "Each step keeps
the suite green" is the goal, not a free property.

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
