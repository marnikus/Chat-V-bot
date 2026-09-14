# Grid row drag & drop, minimum-size reflow, adaptive preset restore — DESIGN 2026-09-14

Owner request (Issue 4 + bug 5 + the GRID FILES / ADAPTIVE RESTORE / ROW
CREATION acceptance block). Process: understand → design → implement
(AGENT_RULES §1), RULE 16 gates and RULE 18 sizes re-checked at the end.

## 1. What the investigation found (evidence, not assumptions)

Repro run against the REAL shipped modules (`ui/js/sash-core.js`,
`ui/js/sash-grid.js`, node, no DOM):

| Probe | Result |
|---|---|
| `moveWindow(log → edge-col of composer)` | works: `col [log, composer]` at 50/50 — **row creation above/below already exists in the model** |
| `moveWindow(sibling before/after, col parent)` | works: middle-row insert |
| `moveWindow(kind:'sash')` between stacked rows | works: middle-row insert, donor gives half |
| px arithmetic, 800 px grid | composer slot = 13 % = 104 px → each new row **52 px < the 96 px CSS minimum** |
| three edge-col moves | **7 of 14 leaves under 96 px** — half the grid is over-constrained |
| `validatePortablePreset(13-window preset)` | `{ok:false, error:"grid metadata is invalid"}` — blanket refusal |

Conclusions:

* **Issue 4** is NOT "rows cannot be created" in this tree — top/bottom edge
  zones, col-sibling before/after, horizontal-sash drops, the full-width
  indicator bar and donor-half reflow all exist (`_computeSpec`, `_showSpec`,
  `SashCore.moveWindow`). What is missing is (a) **minimum-size preservation**
  when a row is inserted into a short slot — the issue's own "Recalculate row
  heights and preserve minimum window sizes" — and (b) **tests** for first /
  middle / last row insertion. Undo already rides the one global timeline
  (`app.js` kind `grid` → `SashGrid._applySerialized`); it needs a fidelity
  test, not new machinery.
* **Bug 5** ("after moving rows/columns the horizontal sash lines disappear
  and cannot be moved") is the overflow consequence: CSS gives EVERY split
  child a 96 px minimum on BOTH axes (`sash-layout.css` `.sash-split > *`),
  while drops split slots blindly 50/50 in percent. An over-constrained
  `.sash-col` forces its children to 96 px each; the split's box keeps its
  smaller percent height, so the children **overflow the box and paint over
  the following rows — covering their horizontal sashes** (unhoverable,
  ungrabbable) until, at the grid root, `overflow:hidden` clips them away.
* **Adaptive restore** fails on BOTH mirrors of the validator
  (`SashGrid.validatePortablePreset` and `services/window_preset_service.py`):
  any document whose window set drifts from the current 14 (a 13-window
  export, a removed window, an added one) is refused wholesale with a
  generic error instead of restoring what matches and explaining the rest.

## 2. Design

### 2.1 Minimum-preserving reflow (bug 5 + the issue's reflow criterion)

Pure, DOM-free, in `sash-core.js` (RULE 6 — the node tests execute it):

```
minimumExtent(node, axis, {minPx, sashPx})
    leaf                     → minPx
    split ALONG axis         → Σ children + sashPx·(n−1)
    split ACROSS axis        → max(children)          // siblings share the cross extent

enforceMinimums(root, widthPx, heightPx, {minPx, sashPx}) → {tree, changed}
    top-down walk tracking (w, h) per node; at each split along its own axis:
      px_i   = (P − gaps) · sizes_i / 100          // flexbox reality: sashes are fixed 6 px
      req_i  = minimumExtent(child_i, axis)
      deficit ⇒ donors with surplus give proportionally;
      total minimum exceeds P ⇒ best effort: sizes proportional to requirements
      (fair degradation — the layout physically does not fit)
```

DOM layer (`sash-grid.js`): `_enforceMinimums()` reads the grid rect and
commits `SashCore.enforceMinimums(...)` when `changed`. Called on the
BLIND-MATH commit paths — the ones that install sizes the user never
chose pixel by pixel: `_dragUp` + `simulateDrop` (a drop splits 50/50 in
percent, ignoring pixels — the bug-5 source), `_onDblClick` (even reset),
`setLayout`, `resetToDefault`, `applyPortablePreset` (foreign screen),
`init`, `_loadFromBackend` (boot heal of stored violations).

Deliberately NOT called after `_resizeUp`/`simulateResize`: the pointer
path already clamps the dragged pair to `MIN_PX` live, and re-fitting
sizes behind an explicit user drag both fights the gesture and breaks the
pinned resize contract (`test_sash_webengine.py` commits 30 % and reads
30 % back). NOT called in `_applySerialized` either — undo/session
restore must reproduce the exact stored arrangement ("Undo restores the
previous grid arrangement").

Feasibility note (measured): the default 14-window tree needs ≈708 px of
grid height; each additional stacked pair adds ≈102 px. When the total
minimum genuinely exceeds the viewport, enforcement degrades FAIRLY
(sizes proportional to requirements, every row equally slightly under)
instead of the old failure mode (one 52 px row next to untouched 190 px
neighbours, overflowing and covering their sashes).

CSS (`sash-layout.css`) — the minimums become axis-scoped, matching the
model, plus containment as the degenerate-case safety net:

```css
.sash-row > .sash-window, .sash-row > .sash-split { min-width:  var(--sash-min-panel); }
.sash-col > .sash-window, .sash-col > .sash-split { min-height: var(--sash-min-panel); }
.sash-split { overflow: hidden; }        /* a split that still cannot fit clips
                                            ITS OWN box instead of painting over
                                            the neighbours' sashes */
```

and the `.sash-window > .panel` dual-axis minimums get the same axis scoping
(the panel minimums were a second overflow vector). The hidden-window zeroing
rules keep their higher specificity / later order.

### 2.2 Adaptive restore (GRID FILES + ADAPTIVE RESTORE criteria)

New DOM-free mirror modules — `ui/js/preset-adapt.js` (UMD, loads between
sash-core and sash-grid) and `services/preset_adapt.py`:

```
adaptTree(tree, version)   → {tree, pruned[], added[]} | structural error
adaptStates(states)        → {states, skipped[]} | corruption error
adaptWindows(entries, states) → {windows, skipped[], added[], corrected[]} | corruption error
buildReport(...)           → {applied[], skipped[{id,reason}], added[{id,reason}],
                              corrected[{id,reason}]}
```

The line between ADAPT and REFUSE:

* **Set drift adapts** (version skew — the acceptance criteria): unknown ids
  anywhere (tree leaves, `windows[]`, `window_states`) are pruned/skipped and
  reported; current windows missing from the preset are appended by the
  existing migrators (JS `SashCore.migrate`, py `LayoutService.migrate_grid_tree`
  + a new `prune_grid_tree` mirror of `SashCore.pruneTree`) into a default
  bottom row and reported; a known entry whose `state` contradicts
  `window_states` is corrected from `window_states` (authoritative) and
  reported; a known entry with corrupt bounds keeps its TREE placement and
  gets default bounds, reported.
* **Corruption still refuses** (I-11 — never persist what cannot be read
  back): bad JSON/format/schema/name/screen, non-list `windows`/states,
  duplicate ids inside `window_states`, closed/minimized overlap, and any
  structurally invalid tree.
* `grid.window_count` is now checked for INTERNAL consistency (equals the
  document's own `windows.length`), not against the live window set; the
  canonical output document always carries the current count, the full
  current window set and the migrated tree — so re-saving an imported
  document round-trips strictly.

Shared reason strings (pinned on both sides, RULE 3 mirror):
`unknown window in this build`, `duplicate preset entry`,
`invalid bounds; default position used`, `state corrected from window_states`,
`not in the preset; added with default placement`.

Result shapes: JS `validatePortablePreset` → `{ok, document, report, warning}`;
`applyPortablePreset` → `{ok:true, report}` / `{ok:false, error}` (the sole
production caller `window-presets.js::_applyPreview` switches to `result.ok`
and renders the report: every skipped/added/corrected window is named in the
status line and the log). Python `validate_document` keeps its
`(document, error)` tuple; the document gains `restore_report`, recomputed on
every load so `load_window_preset` answers with the explanation instead of a
generic refusal. `LayoutService` and the live persistence path
(`save_grid_layout`) stay strict — adaptation lives ONLY on the preset
import/restore seam.

### 2.3 Row-creation tests (the issue's test criterion)

`tests/test_sash_grid_rows.js` (node, real modules, the window-controls stub
pattern): FIRST row (edge top on the first root row), LAST row (edge bottom
on the last row), MIDDLE row (col-sibling before/after AND a horizontal-sash
drop between two stacked rows), the full-width indicator bar for a col spec
(`_showSpec`), minimum preservation after each (every leaf ≥ 96 px at a
800-px grid — the bug-5 repro scenario as a regression), the repeated-move
accumulation scenario (3 moves → 0 leaves under minimum), undo fidelity
(`_applySerialized(previous)` byte-restores the pre-drop tree) and
`setLayout` enforcement. Pure `minimumExtent`/`enforceMinimums` model tests
join `tests/test_sash_core.js`.

## 3. RULE 16 / RULE 18 budget

* New functions ≤ 30 LOC, ≤ 4 params, CC ≤ 10 (`enforceMinimums` decomposes
  into `minimumExtent` + `_fitAllocation` + walk; the adapters are one
  (value, report, error) step each).
* `services/preset_adapt.py` and `ui/js/preset-adapt.js` are new small
  modules (ideal band); `window_preset_service.py` grows inside its
  documented ideal-size override (override text updated, F0 ruling
  2026-09-13 lifts the freeze; the DAG stays one short-circuiting chain);
  `sash-core.js` +≈70, `sash-grid.js` +≈40 (JS UI files, not gate-scanned,
  kept minimal by putting every pure line in the two model modules).
* Gate: changed/new Python functions registered in `rule16_gate.py` OWNED;
  no class grows (validators are module functions / classmethods).
* Coverage: battery floors (line ≥ 92.6449, branch ≥ 88.0261 — the Speed
  round's outcome) must hold; `js_coverage` floor 82.8 % — both new JS
  modules ship with direct node tests.
* Mutation spot-check on `services/preset_adapt.py` (new pure logic, ≥ 70 %).
* Deliberate contract changes (owner acceptance criteria): the strict-set
  refusals pinned in `tests/test_window_preset_service.py`
  (unknown/missing/bounds/state cases), `tests/test_window_presets.js`
  (unknown-leaf refusal) and any `restore_report`-blind assertions are
  rewritten to the adaptive contract; structural-corruption refusals stay
  pinned.

## 4. Acceptance-criteria map

| Criterion | Where it lands |
|---|---|
| Grid exports to a file | existing `export_window_preset` (atomic tmp+replace) — regression-tested |
| Import restores after restart | existing store persistence + adaptive `load_window_preset` — test |
| No generic bridge-required error on restore | adaptive validation replaces blanket refusals; every remaining error is window-specific |
| Missing preset windows skipped safely | `adaptWindows`/`adaptTree` pruned/skipped + report |
| Extra live windows remain usable | migrators append them to a default row + report |
| Known windows get saved position/size | canonical tree + bounds applied as before |
| Result explains every skip/unmatched | `restore_report` on both mirrors, rendered in the UI status line |
| Rows above/below/middle by drag | existing spec kinds — pinned by the new row tests |
| Preview shows the future row | full-width indicator bar — pinned |
| Undo restores previous arrangement | global timeline + `_applySerialized` fidelity test (enforcement excluded there) |
| Recalculate heights, preserve minimums | `enforceMinimums` on every commit path + axis-scoped CSS |
| Tests for first/last/middle insertion | `tests/test_sash_grid_rows.js` |

## 5. Verification (executed 2026-09-14)

**Front end — 30 Node harness files, all green:**

* `tests/test_sash_grid_rows.js` (new, 11 tests): a row above the first
  window, below the last one, a middle row by sibling insert and by
  horizontal-sash insert; the row preview is a full-width 3 px bar and the
  badge names the position; after one and after three row-creating drops at
  1400×1000 no leaf is under the 96 px minimum (the bug-5 regression);
  rendered `.sash-h` count equals the tree's stacked boundaries with none
  hidden; undo via `_applySerialized` restores the tree byte-for-byte;
  `setLayout('a')` at an infeasible viewport degrades to equal rows
  (spread < 1 %) instead of overflowing; an explicit `simulateResize`
  commit stays exact — enforcement provably does not run behind drags.
* `tests/test_sash_core.js` 35 (added `minimumExtent` axis semantics,
  the 50/50-in-a-104-px-slot repair, fair proportional degradation at an
  infeasible viewport, idempotency, headless no-op, and the finding that
  the DEFAULT tree itself violates the minimum at 1200 px height — the
  config panel lands at 83.5 px — and is repaired at `init`).
* `tests/test_window_presets.js` 8 (adaptive validate/apply: unknown tree
  leaf pruned + window re-added + both reported; a 13-window-era preset
  restores with `botprompt` added and 13 applied; corrupt bounds corrected
  to `DEFAULT_BOUNDS`; structural corruption still refuses with the tree
  untouched; `applyPortablePreset` returns `{ok, report}`; the five REASON
  strings pinned literally — mirrored by `test_preset_adapt.py`).
* `tests/test_window_preset_ui.js` 6 (the status line explains every
  skipped window with its shared reason string after apply).

**Python — full battery without instrumentation: `3197 passed, 2 skipped,
1 deselected, 1 xfailed, 902 subtests passed` (6:16).**

* `tests/unit/services/test_preset_adapt.py` (new, 23 tests) +
  `tests/test_window_preset_service.py` (11, rewritten drift/bounds cases
  to the adaptive contract): both new/rewritten modules measure **100 %
  line and 100 % branch**.
* Refusal pins kept: duplicate states ids, closed∩minimized overlap,
  non-list `windows`/`states`, non-dict entries, screen, header, and —
  flipped by design — `windows.pop()` now reports the internal
  `window_count must be 13` consistency error instead of the old
  "current window set" refusal.

**RULE 16 / RULE 18:** `rule16_gate.py` green with 38 new OWNED entries
(all of `services/preset_adapt.py` and `services/window_preset_service.py`);
`tests/test_rule16_new_code.py` 23 passed. `preset_adapt.py` = 300 lines
(in band); four functions that first measured over gate (`_normalize_sizes`
CC 16, `prune_grid_tree` CC 19/cognitive 22/31 LOC, `adapt_tree` CC 11,
`adapt_windows` 39 LOC/CC 13) were decomposed at their natural seams before
registration — no override used.

**js_coverage:** TOTAL **84.0 %** over 31 files (previous measurement
82.8 %); `ui/js/preset-adapt.js` 100 %, `sash-core.js` 95.9 %.

**Mutation spot-checks** (mutmut 3.8.0, `--noconftest`, scratch
`[mutmut]` job, committed F6 config restored afterwards, `mutants/` +
`.mutmut-cache` removed): `services/preset_adapt.py` **424/513 = 82.7 %**,
`services/window_preset_service.py` **249/329 = 75.7 %** (floor 70 %).

**clone_scan:** exit 0 — no new clone groups. The JS↔Python mirror pair is
deliberate duplication across languages, outside clone_scan's Python scope.

**dump_public_api --write:** the only drift found was the speed port's
`actions.scroll_parse_run` missing from the committed snapshot — now
captured; `test_backend_api_snapshot.py` 9/9 green with the update.

**Environmental note (this sandbox, 2 vCPU, Python 3.11):** the
coverage-instrumented battery deterministically fails 39 timing pins in
unrelated async modules (world write gate, boot chain, wait/cancellation,
run safety, bot bridge) because the line tracer pushes them past their
wall-clock deadlines; the same files pass in isolation with and without
this round's tree changes. Coverage taken from that instrumented run
measures line 92.38 % / branch 87.69 % — the deficit versus the recorded
floors (92.6449 / 88.0261) is exactly the aborted paths of those 39 tests
(e.g. `bridge/history_bridge.py` 122 missed lines), not this round's code:
every file this round owns measures 100/100. The floors stand as recorded;
re-measure on hardware where the timing pins pass under instrumentation.
