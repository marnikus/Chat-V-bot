# Area A port notes — Round H frontend quality round onto the grid-rows line

2026-09-15 · port of `8e8cc09` ("Area A (H-A1..H-A5)") + `3d7f799` (Round H
plan docs) from `arena/01a0a1b7-chat-v-bot` onto `arena/01a09b73-chat-v-bot`
at `9cd3722` (grid rows + adaptive preset restore).

Authoritative spec: [`docs/archive/2026-09-14-round-h/AREA_A_FRONTEND_JS_DESIGN_2026-09-14.md`](../2026-09-14-round-h/AREA_A_FRONTEND_JS_DESIGN_2026-09-14.md)
(ported with the plan commit). This note records only what a port must record:
the collision map, the adaptations, the re-baseline decision, and the
executed verification. RULE 17: the source docs stay true as of their date.

## 1. Why this port is not a cherry-pick

The source branch is based at `5197ce0` — **before** the grid-rows round
(`9cd3722`) landed on this line. Both rounds touch the same organ: H-A3
splits `ui/js/sash-grid.js` (1,361 lines) into a facade + four parts, while
the grid-rows round had just rewired that same file (minimum-size reflow on
the blind-math commit paths, adaptive preset validation). A cherry-pick of
either side would silently drop the other. So: cherry-pick for the 40
non-colliding files, and a hand-carried remap of the grid-rows delta into the
new part structure for the 3 colliding ones.

## 2. Collision map (3 files)

| File | Source side (Area A) | This line (grid rows) | Resolution |
|---|---|---|---|
| `ui/js/sash-grid.js` | gutted to a 112-line facade | 10 surgical changes inside the old monolith | facade taken; the 10 changes remapped into the parts (§3) |
| `ui/index.html` | +12 part `<script>` tags | +1 `preset-adapt.js` tag, same insertion point | union: `sash-core → preset-adapt → 4 parts → facade` |
| `tests/test_window_presets.js` | 6-line loader swap to `js_family` | adaptive-contract rewrite + REASON pins | their loader + this line's content |

Plus one non-conflicting but load-bearing edit: `tests/js_family.js`
`FAMILIES.sashGrid` gains `'preset-adapt.js'` after `'sash-core.js'` — the
loader must mirror `ui/index.html` (its own stated contract), and the
presets part resolves `PresetAdapt` by name at call time.

## 3. The grid-rows delta, remapped (10 changes → 4 files)

| Change (from `git diff 5197ce0 9cd3722 -- ui/js/sash-grid.js`) | New home |
|---|---|
| `_enforceMinimums()` helper (12 LOC) | `sash-grid-tree.js` (tree-recompute domain) |
| `init` reflow after `_loadTree` | facade `init` |
| `_loadFromBackend` reflow after backend load | `sash-grid-windows.js` |
| `resetToDefault` reflow | `sash-grid-windows.js` |
| `setLayout` reflow | `sash-grid-windows.js` |
| `_dragUp` reflow after `_applyDrop` | `sash-grid-drag.js` |
| `_onDblClick` even-reset reflow | `sash-grid-drag.js` |
| `simulateDrop` reflow | `sash-grid-drag.js` |
| adaptive `validatePortablePreset` (PresetAdapt, report, internal `window_count` check) | `sash-grid-presets.js` |
| `applyPortablePreset` → `{ok, report|error}` + reflow + `reportSummary` log | `sash-grid-presets.js` |

The presets part kept the source's own decomposition (`_screenSnapshot`,
`_portableBounds`, `_portableScreen`) and the adaptive rewrite re-shaped
`_cleanPortablePreset(doc, treeRes, statesRes, winsRes)` around it; the
strict trio (`_portableStates`, `_portableWindows`, `_validPortableBounds`)
is gone — `PresetAdapt` owns set membership on this line, corruption
refusals preserved verbatim. Deliberately **not** remapped: any reflow
behind `simulateResize`/`_resizeUp` and inside `_applySerialized` — the
grid-rows design forbids it (explicit drags stay exact, undo stays
byte-for-byte), and both pins re-passed after the split.

## 4. The re-baseline decision (the source's "known red until H-A6")

The source branch shipped `reports/js_size_baseline.json` +
`js_coverage_baseline.json` **pre-dating its own splits**, with
`tests/test_js_gate.py::TestGateEndToEnd` documented as failing mid-round.
This line does not land red batteries: both baselines were regenerated on
the merged tree (`js_size.py --json`, `js_coverage.py --json`) — the
mechanical half of H-A6, pulled into the port. Consequences, stated plainly:

* the ratchet now **freezes the post-split state**, including its known
  debt: 50 functions over 30 LOC (same count as the pre-split audit — the
  splits moved functions, H-A6 must still shrink them; 6 of the 50 are
  UMD-factory measurement artifacts of the AST-free scanner), 11 part
  objects 151–270 LOC, `stack-dnd-menu` 16 methods,
  `stack-dnd-form::_showConfig` 37 LOC;
* per-file coverage ratchets up-from-current for every one of the 43 files
  (none never-loaded any more);
* the H-A6 **lift targets** (total ≥ 90%, the six weak files ≥ 80–85%) are
  untouched future work, exactly as the source scoped them.

## 5. Verification (executed 2026-09-15, this sandbox)

| Check | Result |
|---|---|
| Node harnesses | **35/35 green** (30 of this line + `test_app_facade` 46, `test_url_toolbar` 16, `test_composer` 8, `test_criteria_editor` 8, `test_log_console` 7) |
| Python battery (no instrumentation, webengine deselected) | **3213 passed, 2 skipped, 1 xfailed, 902 subtests** — 0 failures (5:53) |
| `js_gate.py` (regenerated baselines) | **PASS** — 43 files / 12,504 lines / 1,163 functions; coverage **83.71%** honest per-file attribution; no never-loaded file |
| `rule16_gate.py` + `test_rule16_new_code.py` | green (Area A edits no Python production module; the grid-rows OWNED set untouched) |
| `dump_public_api.py` | "no removed or changed symbols" |
| `clone_scan.py` | exit 0 — no new groups |
| Grid-rows pins after the split | `test_sash_grid_rows.js` 11/11 (loader converted to `js_family`), `test_window_presets.js` 8/8 (incl. the five literal REASON strings), `test_sash_core.js` 35/35 |

Structural targets re-measured from the committed baseline: SashGrid facade
**112 lines / 6 methods** (was 1,361 / 1,331-LOC object / 69 methods), parts
259·490·137·457 lines with objects ≤ 15 methods each; StackDnD facade
**269 / 5** (was 1,132 / 1,168 / 58) + five parts, `_showConfig` 180 → 37
LOC via the `ROW_BUILDERS` table; `app.js` **93 / 1** (was 509, with the
205-LOC `setupBridgeListeners` dissolved into 13 per-window `wire*` groups
in `app-bridge.js` 284/15). Coverage of the split members: facade 99.1%,
presets part 97.8%, `preset-adapt.js` 100%, `app.js` 100%.

## 6. RULE 18 / RULE 16 notes

* `tools/metrics/js_size.py` is **596 lines** — over the file ideal. It is
  tooling in the `tools/metrics` family (precedent: `rule16_gate.py` ~670,
  `js_coverage.py` ~460), single-responsibility (one brace-matching walker +
  one report shape), and ported as-is; the JS gate it feeds ratchets it
  nowhere (Python-side tools are not in its scope). Flagged for a future
  tools pass, not grown further here.
* `ui/js/sash-grid-windows.js` (490) and `sash-grid-drag.js` (457) sit
  between the file ideal (300) and the gate fail line (500), as shipped by
  the source. The gate freezes them: they may shrink, never grow.
* Every function this port itself added or moved is ≤ 30 LOC
  (`_enforceMinimums` 12; the adaptive `validatePortablePreset` 24;
  `_cleanPortablePreset` 17) — no new JS function over the line, and the
  Python OWNED set is unchanged.

## 7. What remains from Round H

* **H-A6** (source's own next step): shrink the frozen 50, lift the six
  weak-coverage files, total ≥ 90%.
* **Areas B/C/D**: untouched by this port (disjoint file ownership per the
  Round H design); their plan docs are archived with the plan commit.
