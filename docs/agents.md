# Writing slides with static_website_lhtml: guide for AI agents

This guide is for an agent (LLM) that writes or edits the slides of a
project built with static_website_lhtml. It is copied into every built site
as `structure/agents.md`. The README of the generator is the full reference;
this page is the procedure.

## The project

- `configure.yaml`: the configuration. `source_directory` holds the slides,
  and `site_directory` is the generated site. Never edit the site: it is
  rebuilt from the sources.
- One slide is one directory with an `index.html.j2` file (LHTML markup,
  Jinja2), its `assets/`, and an optional `config.yaml`.
- `deck.yaml` (if the configuration has `deck:`): the order of the slides,
  given as pointers to their directories. It can include slides of other
  projects (`name:path`) and repeated slides with `params`. Without a deck,
  the slides follow the order of the files.
- After a build, `<site>/structure/design.md` is the reference of the design:
  macros, layouts and tokens. **Read it before writing a slide.**

## Commands

Run them from the directory of `configure.yaml`, with
`python <generator>/generate.py`:

| Command | Use |
|---|---|
| `generate.py` | Full build (a few seconds) |
| `generate.py --only 03_part/04_slide` | Build these slides only (pointers as in the deck; repeatable) |
| `generate.py --only 03_part/04_slide --layout` | Build and measure them: layout report in `.layout/` |
| `generate.py --layout` | Measure the whole deck (slow: about 1 s per slide) |
| `generate.py --lint` | List the values written by hand, with their replacement (no build) |
| `generate.py --scaffold` | Create the planned slides of the deck (entries with a `title` and no source yet) |
| `generate.py --check-config` | Check the configuration, deck and design without building |

`--only` falls back to a full build when the list of pages changed (deck
edited, slide added or removed).

## Procedure

**New deck or new part.**
1. Write the plan in `deck.yaml` before any slide. Each entry has a `path`, a
   `title`, the key message (`message:`), and optionally `duration:`
   (minutes) and `layout:`.
2. Have the plan validated.
3. Run `--scaffold`. It creates `<path>/index.html.j2` with the title and the
   metadata as comments.
4. Write the slides, then build and check them as for an edit.

**Writing or editing a slide.**
1. Choose a layout (see below) and put it on the first line:
   `{% set layout = 'side' %}`.
2. Write the content with the macros of `design.md`. Do not write positions,
   pixel sizes, spacers or font sizes.
3. Run `--only <slide> --layout`, then read
   `.layout/pages/<slide>/index.html/layout.md`. Look at `render.png` in the
   same directory, or at `overlay.png` when blocks are close.
4. Fix the problems, then repeat step 3.
5. Run `--lint --only <slide>`: the slide should have no finding, or only
   exceptions you can justify.

**Whole deck.** Run `--layout`, then read `.layout/summary.md`: the pages
are sorted by number of problems, and the `lint` column counts the values
written by hand. The contact sheets `.layout/contact_NN.png` show the whole
deck at a glance.

## Layouts

A layout places and sizes the blocks of a slide. Its figures go in
`media:: ... ::`, which fits them in the area of the layout.

| Layout | When |
|---|---|
| `side` (`side-s`, `side-l`) | Text on the left, figures on the right. The most common case, including code + figure. |
| `stack` | Text, then figures filling the rest of the slide. Use `media::(.row)` for a row of figures. |
| `section` | Title or section slide, centered. |
| (none) | Text only, text + code, columns (`cols::` / `col::`). |

```
{% set layout = 'side' %}
= Forward kinematics

* Each joint angle is set by hand
gap::
* Rotations are interpolated

media::
img::assets/fk.jpg
credit:: Image: Wikimedia Commons ::
::
```

`media::` variants:
- `(.row)`: figures side by side; add `.even` for equal widths.
- `(.fill)`: enlarge small figures.
- `(.top)`, `(.middle)`, `(.bottom)`: vertical position.
- `(.auto)` in `stack`: take only the height of the figures.
- `(.here)` in `side`: in the right column, facing the text that follows it
  (write it just before that text); several figures can face several parts.

In `side`, `intro:: ... ::` holds text on the whole width above the columns;
the figures start below it.

Put a figure and its caption in a `col::` inside a row. A `placeholder:: text ::`
stands for a figure that does not exist yet.

## Rules

- Use the design, not values. Use `gap::` (`s`, `l`, `xl`), not
  `div::[height:25px;]::`. Use `small::`, `tiny::`, `large::`, not
  `font-size`. Use a layout, not `position:fixed`. Use `cols::`, not
  `display:flex`. `--lint` names the replacement of each value.
- Keep an inline value only when nothing in the design expresses it (an
  annotation drawn over a figure, for example), and keep it minimal.
- Several classes: `(.a .b)` or `(.a.b)`.
- Do not change the text of a slide unless asked. Do not edit the generated
  site, other projects (deck `sources`), or `design.yaml` of the theme. Design
  changes go in the `design` key of `configure.yaml` (tokens, new macros).
- A repeated slide reads its parameters as `params.name`
  (`{% set current = params.current | default(0) %}`).
- Jinja loops inside an LHTML list need `{%-` to avoid breaking the list.

## Reading the layout report

`layout.md` gives one row per top-level block: number, the line of the source
where it starts, kind, position and size of what is drawn, font, and a
signature. An element in `position: fixed`/`absolute` inside a block is a
block of its own (`in #n`): its overlaps with the text of its block are
reported.

**Problems** must be fixed:
- `HIDDEN TEXT`: text covered by another block.
- `COLLISION`: drawn contents overlapping.
- `OUT OF AREA`: a block beyond the slide frame.
- `CLIPPED`: content cut by `overflow`.
- `UPSCALED IMAGE`: a bitmap or video enlarged above 1.25×, so it looks blurry.
- `RESERVED AREA`: content over the navigation of the theme.

**Warnings** should be checked:
- `TIGHT`: lines too close to another block.
- `NEAR-ALIGNED`: edges a few pixels apart; align them exactly or move them clearly.
- `DENSE`: too many words.
- `SMALL FONT`: text too small.
- `WRAPPED`: a title on several lines, or an item with a few words on its
  second line: shorten it, or give it more width.
- `ROW`: figures side by side not aligned.
- `SMALL IN ITS BOX` / `CROPPED`: a figure much smaller than its area
  (`media::(.fill)`, or another arrangement), or cut.

**Differences with the deck** (title position, text sizes used nowhere
else) are breaks of consistency, not errors.

**Values written by hand** are the lint findings of the page. The density
section gives the largest free area of the slide.

After an edit, `.layout/changes.md` lists what moved and which problems
appeared or disappeared: check that only the intended blocks changed. The
renders are reproducible (videos and GIFs at their first frame), so a change
there is a real change.

An intended overlap (an inset over a figure) takes the class `overlay`.

## Comments of the author

With `generate.py --serve`, the author can click a block of a page and write a
comment. They are in `.feedback/comments.md` (next to `configure.yaml`), each
with its page and the file and line of the block. Treat the open ones (the
edit, then `--only <slide> --layout`), then set their `"status"` to `"done"`
in `.feedback/comments.jsonl`, and say what you did for each.

## When to stop

A slide is done when:
- its report has no problem;
- its warnings are understood;
- `--lint` reports nothing unjustified;
- its render reads well: figures large enough, no large empty area, text not
  crowded.

Report what was changed and any value kept by hand, with the reason.
