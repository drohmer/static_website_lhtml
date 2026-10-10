# Agent extension: structured verification

This directory adds `--verify` to the generator, for agents (LLM) that fix
slides on their own. `generate.py` and the layout report import it only under
`--verify`; without this directory the base builds, `--layout` included, work
the same (`tests/test_tracking.py` checks it). The base keeps a few hooks for
it: source markers of any kind (`lib/source_map.py`), the interactive states
in `layout_measure.js`, and the sections of `layout.md` written under
`--verify`. A plain `--layout` removes the outputs of a previous `--verify` of
the pages it measures.

```bash
python generate.py --only 03_squelette/04_ik --verify
```

`--verify` is `--layout` (`render.png`, `summary.md`, and `layout.md` with
three more sections: `Source provenance`, `Interactive verification`,
`Internal hierarchy`) plus:

| File (in `.layout/`) | Content |
|---|---|
| `verification.json` | status of the measured pages (the worst one) and of each page, in deck order (pages whose measure failed last); pages kept from a previous measure are listed with `measured: false` and do not count in the status |
| `pages/<page>/verification.json` | status (the worst of the page, its frames and its states), diagnostics of the page and of its states (type, severity, blocks, source lines, bounds, crop), render health |
| `pages/<page>/changes.json` | diagnostics since the previous measure: `introduced`, `resolved`, `persisting`, `updated` (same diagnostic, other values) |
| `pages/<page>/issues/*.png` | crop of each diagnostic (at most 20), cut from `render.png` or from the render of its state |
| `pages/<page>/states/<state>/` | report and render of each interactive state |
| `pages/<page>/frames/f<n>/` | report and render of each local iframe (demos), at most 16 |
| `triage.md`, `triage.json` | diagnostics grouped by source line and rule, across slides and states |

## Statuses

- `pass`: the checks run found nothing. Not a visual approval.
- `issues`: problems or warnings (a warning is enough: `pass` means no
  diagnostic at all).
- `incomplete`: errors while loading (JavaScript, request, HTTP status, image,
  font, video, KaTeX), content not checked (canvas, inaccessible frame, 400
  inner blocks or more, more interactive states than `max_states`), or a
  report whose sources have changed since its measure (`freshness`: `stale`,
  or `unknown` for an untracked or remote file).
- `failed`: the measure itself failed, or an interactive state failed.

## Procedure

1. Read `verification.json` of the page, then its `render.png` (and the image
   of the state given by `state_id`, if any).
2. Make one targeted correction in the source.
3. Run `--verify` again; check `changes.json`: the defect resolved, nothing
   introduced.
4. Stop when the measured defects are fixed and the render reads well.
   Keep the content and the typography of the theme: never shrink the text
   only to remove a collision. Report what remains unchecked (canvas,
   interactions not sampled).

## Identity of the blocks

Each line of a source receives an anchor kept in `.source-map/identities.json`
(next to the configuration). A block keeps its identity when lines are
inserted, moved or slightly edited, so a diagnostic can be followed from one
measure to the next. An ambiguous rewrite gives new identities; an explicit id
(`div::(#figure)` or an HTML `id`) survives any rewrite. Deleting the file
starts new identities. Jinja and LHTML includes keep the file they come from.

## Interactive states

`--verify` samples the animations of each page: CSS animations, videos and GIFs
at 50 and 90 % of their duration, `requestAnimationFrame` loops at 500 and
1500 ms (a controlled clock replaces `requestAnimationFrame` and
`performance.now`). Explicit scenarios click, type or press keys, then check
what is visible:

```yaml
plugin_arg:
  layout_report:
    interactive:
      auto_media: true          # automatic samples (default)
      max_states: 6             # 1 to 16 (default 8)
      pages:
        '00_ouverture/09_interpolation/index.html':
          - name: spline
            actions:
              - {type: click, frame: 'iframe.demo', selector: 'button[data-mode="spline"]'}
            expect:
              - {frame: 'iframe.demo', selector: 'button.active', visible: true}
```

Actions: `click`, `input` (`value`), `key` (`key`), in a frame given by its
selector (`frame`) or in the page; `time_ms` (0 to 5000) advances the clock
after the actions, before the expectations and the capture. At most 16 states per page pattern, 16 actions and 16
expectations per state, 16 local frames. A failed action or expectation is an
`INTERACTIVE STATE` problem and makes the page `failed`. Not controlled:
native timers, `Date.now`, randomness, external frames; the content of a canvas
is not understood (its overlaps are `CANVAS OVERLAP` warnings). Set
`enabled: false` to keep only the initial render (the local frames are still
measured).

## Triage

`triage.md` groups the diagnostics by source line and rule, with a priority:
0 interactive scenario that failed, 1 problem measured on the geometry, 2 rule
to review (warnings, other checks), 3 overlap with a canvas, to look at on the render. It
proposes what to look at; the correction is written by the agent.

## Files

```
agent/
  report.py           # steps of --verify in the layout report (plugins/layout_report.py)
  verification.py     # verification.json, changes.json
  provenance.py       # persistent anchors of the source lines
  interactive.py      # validation of the interactive scenarios
  triage.py           # triage.md, triage.json
  assets/             # interactive_states.js, verification_crops.js (Node)
  tests/
```

## Tests

```bash
python -m pytest agent/tests -q
LHTML_BROWSER_TEST=1 python -m pytest agent/tests -q     # with Chrome
```
