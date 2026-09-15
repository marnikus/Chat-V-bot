# Round I — plan (2026-09-16). PLAN ONLY: no implementation in this step.

Inputs: `reports/CODE_QUALITY_METRICS_2026-09-16.md` (fresh measurement of
`origin/main` f8f1d88 after the JS-split fixes). Binding rules:
`docs/current/AGENT_RULES.md` — RULE 8 (real thing), RULE 16 (gates),
RULE 17 (docs), RULE 18 (sizes, line budgets), RULE 19 (remediation order).

## 0. Diagnosis — where the biggest problem actually is

The metrics are unambiguous: **structure improved, truth collapsed.** The
Area A splits deleted 1,047 JS lines and cut >30-LOC JS functions 49 → 37,
but shipped with **73 red tests, a JS gate at 86 violations, JS coverage
82.52 → 69.49 % and Python coverage under its own recorded 93.16 %
baseline**. The biggest problem in the repo is not a god class; it is the
gap between what changed and what was verified. Every area below attacks
that gap, biggest block first.

## Round rules (apply to every area)

1. **Green is the face of done.** A step ends with the affected tier green,
   not with the code written.
2. **Fix or re-baseline — never both silently.** Every red contract gets a
   decision written in the commit: regression (code fix, RULE 8) or
   legitimate drift (baseline refreshed, drift named).
3. RULE 19 order for every split leftover: nesting → CC → cognitive → size.
4. RULE 16 on every production edit: sizes, CC ≤ 10, no new smells, floors
   never decrease. RULE 18 ideals aimed at; deviations carry `ideal-size:`.
5. Docs move in the same change (RULE 17): SOR rows, no new current docs;
   this folder holds the round's evidence.
6. End-of-round re-check (owner asked for this explicitly): RULE 16.7
   checklist + `wc -l` budgets + radon + coverage compared against this
   plan's baseline table, all pasted into a closure report in `reports/`.

## R0 — Reconciliation (owner decision required before any area starts)

`main` (f8f1d88, the fixes) and `arena/01a0a4de-chat-v-bot` (49d4ec9, the
test-architecture stream) diverge in 357 files. Each has what the other
needs:

| Main has | Session branch has |
|---|---|
| Area A JS splits, tier runner (`run_tiers.py`), `js_gate.py`, `js_size.py`, `smell_inventory.py`, `mutation_platform.py`, `file_coverage_floor.py` | xdist lanes + auto-marking, wait-budget ratchet (≤ 50 ms), JS-coverage pytest ratchet (82.7 floor, 30 per-file pins), node suites as pytest items, RULE 8 integration doctrine, CI workflow spec |

R0.1 Owner picks the convergence target (recommend: main becomes truth;
the session-branch tooling/doc waves replay onto it as clean commits —
content exists, no re-design needed).
R0.2 Replay, in order, as separate reviewable commits: (a) pytest lane
machinery + markers, (b) wait-budget + JS-coverage ratchets, (c) RULE 8
doctrine + SOR §7 lanes, (d) CI workflow (owner-blocked permission —
human copy).
R0.3 From then on, every statement below reads against main.

## AREA R1 — Back to green (the biggest block: test-contract truth)

Scope: the 73 red Python items + 14 red Node suites. Owned files:
`tests/**`, plus the production files the failures point at
(`backend/history_query*`, `services/media*`, `bridge/router*` +
file-bridge legacy, `services` window-presets export path, `ui/js`
only where a contract names it).

Steps (each ends green on its slice):

* R1.1 **Roster.** Re-run the three tier slices with `-rf`, write the full
  73-name list into this folder (`ROUND_I_RED_ROSTER_2026-09-16.md`), one
  line per test with the failure family assigned. Known families from the
  measurement: JS-split DOM/bridge contracts (≈9), legacy bridge/router
  compat surface (≈7+), defensive backend reads (2), media network-watch
  (3), stores surface/counts (5+2), gate self-tests (3+2), qt-tier
  residuals (≈35), env-bound webengine (1).
* R1.2 **JS-split DOM contracts.** For each of the ≈9 UI-wiring reds
  (archive-delete buttons, label pills, user-table render/sort, people
  undo, window-presets export): check the split file actually wires the
  element; fix the split (real bug) or update the contract to the new
  module layout (drift, named). This is the family most likely to be
  *real user-visible breakage*.
* R1.3 **Legacy compat surface.** `TestLegacyCompatSurface` + file-bridge
  (≈7): decide removals were deliberate (contract re-baseline, review note)
  or accidental (restore helpers). No silent deletion either way.
* R1.4 **Defensive reads + media watch (5).** `history_query_gaps` (2),
  `media_network_watch` (3): behaviour diffs — treat as real until proven
  drift; RULE 8 reproduction first.
* R1.5 **Stores surface drift (7).** Frozen public API, import surface,
  file count, module families: the splits added undeclared modules —
  declare them into the families *or* fold them back; re-baseline counts
  with the review note.
* R1.6 **Qt SIGABRT hunt.** The mixed qt tier aborts (−6) where the
  qt-only tier doesn't: bisect the crashing test (likely a QApplication
  lifecycle leak between tiers); fix the teardown, not the skip.
* R1.7 **Node suites (14+).** userdb_refresh/sort, window_preset(s),…:
  same fix-or-drift drill per suite; the suites exercise real JS (RULE 8).

Exit: all tiers green; `run_tiers.py --with-qt` exit 0; roster doc closed.

## AREA R2 — JS verification floor recovery (second biggest)

Scope: `tests/*.js`, `tests/js_harness.js`, `tests/dom_stub.js`,
`tools/metrics/js_coverage.py` baselines. No production edits except where
R1.2 exposes a bug.

* R2.1 Harness the ~20 never-loaded split files (bot-chat-*, bot-prompt-*,
  bot-settings-*, db-panel-*, history-db-*, labels-*, stack-drag-core/
  visual/scroll, user-table-*, window-presets-*): load order from
  `ui/index.html`, one suite per cohesive module, DOM stub extended only
  where the module's real contract needs it.
* R2.2 Re-cover the modules that *lost* coverage in the splits
  (bot-chat.js 97.5 → 0.0, color-picker 100 → 32.8, bot-connection-view
  99.6 → 41.6, bot-messages 82.9 → 48.7, collector-panel 95.4 → 70.0,
  bot-settings 94.9 → 59.3): find the moved bodies, pin each through its
  new home; facades get their own thin pins.
* R2.3 Re-baseline `js_coverage_baseline.json` (reviewed, drift named).
* R2.4 Adopt the session branch's per-file floor ratchet from R0.

Exit: JS coverage ≥ 82.52 % global, zero never-loaded, js_gate coverage
section green.

## AREA R3 — Finish the splits to the gate (size head)

Scope: `ui/js/sash-core.js`, `sash-grid-drag-*.js`, `bot-settings-core.js`,
`labels-*.js`, `history-*-core.js`, `user-table-core.js`,
`window-presets-*.js`, `backend/js/chat_agent.js`. RULE 19 order, and only
after R1+R2 pin the behaviour of each file (no unverified surgery).

* R3.1 `chat_agent.js::(anonymous)` 782 LOC — the current JS hotspot #1.
* R3.2 `sash-core.js` 684 (over its own 642 baseline; anonymous 619 → 661;
  `moveWindow` 43 → 51) — shrink below baseline, don't re-baseline upward.
* R3.3 The two >150-LOC objects (`sash-grid-drag-core` 194,
  `drag-spec` 159) and the 21-method `bot-settings-core` object.
* R3.4 The 37 NEW >30-LOC functions cluster (`labels-edit::_editRow` 54,
  `labels-render::pill` 47, `labels-assign::renderAssign` 50,
  `history-store-core::init` 45, `history-db-core::init` 45,
  `labels-filter::renderFilter` 45, `history-db-render::render` 34,
  `user-table-core::init` 37, `drag-spec::_specGeometry` 36, …).
* R3.5 Fix the 2 failing `test_rule16_new_code.py` self-tests (a request
  object over its own size gate — likely a widened preset object).

Exit: `js_gate.py` size section reports 0 violations; functions-over-30
count < 37 (target ≤ 20); every split green under R1/R2 pins.

## AREA R4 — Gate integrity & hygiene (small, high leverage)

Scope: `tools/metrics/*`, `services/run/hooks.py`, `stores/**`
(ratchet-declared parts only after R1.5).

* R4.1 `js_gate.py` fails loudly: exit 1 on VIOLATION today it exits 0 —
  a gate that can't fail is a report.
* R4.2 vulture: delete the 3 dead `coordinator` findings (`hooks.py`); keep
  the gate checking.
* R4.3 clone baseline: review the drift, re-baseline or extract (RULE 16.4).
* R4.4 Pre-commit/CI wiring on main: confirm hooks run gate+clone+vulture;
  fold in the tier runner as the CI lane plan.
* R4.5 Re-record the §16.3 baseline (93.16 %) after R1/R2 — never
  re-baseline downward without the whole round green first.

Exit: all gate self-tests green; js_gate exits nonzero on failure; vulture
clean at confidence ≥ 90.

## Sequencing & branches (as requested: isolated areas, own branches)

```
main ─┬─ round-i/r1-green      (R1; Tier-slice branches per family allowed)
      ├─ round-i/r2-js-floor   (R2 after R1.2/R1.7 land — needs stable JS)
      ├─ round-i/r3-splits     (R3 after R1+R2 — no unverified surgery)
      └─ round-i/r4-gates      (R4 parallel-safe; disjoint files)
```

Files per area are disjoint by construction (tests vs ui/js vs tools +
hooks). R1 is the gate for everything: nothing rebases onto a red tree.
This Arena session is pinned to `arena/01a0a4de-chat-v-bot` and cannot
create or switch branches — so here the areas land sequentially in order
R0→R1→R2→R3→R4; other Arena sessions can execute the branch plan in true
parallel.

## Effort-vs-impact

| Area | Effort | Impact | Why now |
|---|---|---|---|
| R1 | L | Repo-blocking | 73 red tests = nothing else can be safely verified |
| R2 | M | High | JS coverage −13 pts is the biggest single regression |
| R3 | M | Medium-high | new-code violations fossilize fast if not fixed in-flight |
| R4 | S | High/leverage | cheap; restores the enforcement that would have caught R1–R3 |

## Definition of done (whole round, rechecked against this file)

* All tiers + Node suites green on a clean clone; no flaky abort in 3 runs.
* `js_gate.py` green and hard-failing; rule16 gate exit 0 with vulture on.
* Python coverage ≥ 93.16 % (restored baseline) → then §16.3 re-recorded.
* JS coverage ≥ 82.52 %, zero never-loaded files.
* JS functions > 30 LOC ≤ 20; zero >150-LOC objects; zero 15+-method objects.
* RULE 16.7 checklist pasted into the closure report; RULE 18 budgets held
  (AGENT_RULES ~730, SOR ≤ ceiling); closure report in `reports/`, this
  folder updated to "executed".
