# Code quality audit — 2026-09-11 (round 3, after your latest fixes)

Snapshot: `53ba5fb6` on branch `arena/01a08dc3-chat-v-bot`, working tree clean.
Toolchain: Python 3.11.2, Radon 6.0.1, `cognitive-complexity` 1.3.0, coverage
7.16.0, pytest 9.1.1, Vulture 2.16, pylint 4.0.8, mutmut 3.7.0, Node 22.22.3.
Definitions are the frozen ones in `docs/AGENT_RULES_CODE_QUALITY.md` §1–§3
(= the definitions used by `reports/CODE_QUALITY_METRICS_2026-09-10.md` and
`reports/CODE_QUALITY_METRICS_2026-09-10_cc-tail.md`), and every number below
was produced by the scripts in `tools/metrics/` — no re-typed figures.

**Baseline caveat (read first).** This checkout has exactly one commit
(`git rev-list --count HEAD` = 1), so the previous tree cannot be re-measured.
"before" values are the numbers *recorded* in the round-2 report (and round-1
where round-2 did not record one). Same script, same scope, same definitions —
but not a controlled same-tree A/B, and the denominators moved (production
Python LOC +151 since round 2, statements +11.7 % since round 1).

---

## Headline: what your fixes changed

| Guidance family | Your threshold | Now | Verdict |
|---|---|---|---|
| 1. Complexity (CC / cognitive / nesting) | ≤10 / ≤15 / ≤3–4 | max **28 / 40 / 6**; **90.5 %** of functions clean | Legacy tail **unchanged** — this round did not touch it |
| 2. Size & volume (fn LOC / params) | ≤30 / ≤4 | **74** and **70** offenders (of 1,668) | −1 and −1; flat |
| 3. Coupling & cohesion (Ca/Ce/I, LCOM) | low, low, →0, →0 | mean LCOM\* **0.652**; **10 package-level import cycles** | **New finding**: cycle data (see §3.3) |
| 4. Test quality | ≥80 % line / ≥75 % branch / ≥70 % mutation / ~1:1 | **90.44 % / 88.99 % / 94.34 % / 1.65:1** | both coverage floors **pass**, mutation score **newly measured** |
| 5. Code smells | fewer | clones **12/90** (flat), vulture **7** (flat), envy **60 candidates** | Duplication/dead-code **flat**; envy newly measured |
| 6. Maintainability (MI / TDR / churn / bug density) | higher MI, low TDR | MI **65.09**, TDR **≈ 10.9 %** (modelled) | MI +0.03; TDR **newly estimated**; churn/bug density still unavailable |

**No regression — but the ratchet margin is now razor-thin.** Line coverage is
**90.44 %** against the recorded **90.41 %** baseline: RULE 16 §3 fails any
decrease, so the rule holds by **0.03 pp (≈ 4 statements)**. Do not read this as
"coverage is fine": it means a single uncovered new file would break the gate.
The healthy signal is absolute — uncovered statements **fell** 1,400 → 1,294 and
uncovered branch destinations **fell** 556 → 363 since round 1, while statements
in scope grew to 13,531 (+11.7 %); branch coverage gained **+4.61 pp**. Recovering
real headroom needs ~144 newly *covered* statements in the eight files under 75 %,
not a re-run.

*(Numbering trap, recorded so nobody re-trips it: `coverage json`'s
`percent_covered` = **89.25 %** is coverage.py's combined line+branch figure, not
line coverage. Both prior reports use line = covered ÷ statements = 12,237 ÷
13,531 = 90.44 %. The `--source` scope and the single deselect are unchanged.)*

### before → after (round 2 → round 3)

| Metric | round 2 (recorded) | **round 3 (now)** | Δ |
|---|---:|---:|---:|
| Python tests | 2,467 passed | **2,545 passed, 0 failed** | **+78** |
| Line coverage | 90.41 % | **90.44 %** (12,237 / 13,531) | **+0.03 pp** (ratchet holds by ~4 statements) |
| Branch coverage | 84.38 % | **88.99 %** (2,935 / 3,298) | **+4.61 pp** |
| JS test suites | 20 files, 1 stale failure | **22 files, 22 pass, 0 fail** | stale registration test fixed |
| Mutation score | not measured | **94.34 %** (150 killed / 9 survived, bounded scope) | **new** |
| Max cyclomatic CC | 28 | **28** | 0 |
| Max cognitive complexity | 40 | **40** | 0 |
| Max nesting depth | 6 | **6** | 0 |
| Functions CC > 10 | 64 | **63 / 1,668 (3.8 %)** | −1 |
| Functions cognitive > 15 | 21 | **21 / 1,668 (1.3 %)** | 0 |
| Functions nesting > 4 | 3 | **3 / 1,668 (0.2 %)** | 0 |
| Functions > 30 LOC | 75 | **74 (4.4 %)** | −1 |
| Functions > 4 params | 71 | **70 (4.2 %)** | −1 |
| Mean CC / mean cognitive / mean fn LOC | 3.31 / 2.45 / 10.32 | **3.30 / 2.44 / 10.30** | ≈ flat |
| Production Python files | 141 | **141** | 0 |
| Production physical LOC | 24,783 | **24,934** | +151 |
| Radon SLOC | — | **17,509** | — |
| Classes > 300 LOC / > 15 methods | 11 / 24 | **11 / 24** | 0 |
| Mean per-file Radon MI | 65.06 | **65.09** | +0.03 |
| Exact-AST clone groups / lines | 12 / 90 | **12 / 90** | 0 |
| Vulture findings ≥ 90 % | 7 | **7** (same set) | 0 |
| Test-to-code ratio (nonblank, non-comment) | 1.50:1 (round 1) | **1.65:1** (34,005 / 20,559) | +0.15 |
| Longest function | 122 LOC (`dom_probe.build_probe`) | **122 LOC** (same, §1.5 exempt) | 0 |

**How to read this:** your fixes were a **verification round, not a complexity
round**. They moved test quality (branch coverage +4.6 pp, +78 tests, JS suite
green, mutation score now on the board for the first time) and left the CC/cognitive
tail exactly where round 2 left it — which is consistent with
`docs/CC_REMAINING_TAIL_DESIGN_2026-09-10.md` still being marked
"**design only — not implemented**".

---

## PART 1 — Complexity metrics

Scope: 141 production Python files in `core`, `actions`, `backend`, `bridge`,
`services`, `stores`, `app`, `main.py`; 1,668 functions (nested defs scored
separately, lambdas excluded); 197 classes.

| Metric | Threshold | Result | Within threshold |
|---|---:|---|---:|
| Cyclomatic complexity (Radon) | ≤ 10 | mean **3.30**, max **28**, median-of-all 3 | **1,605 / 1,668 = 96.2 %** |
| Cognitive complexity | ≤ 15 | mean **2.44**, max **40** | **1,647 / 1,668 = 98.7 %** |
| Nesting depth | ≤ 3–4 | mean **0.74**, max **6** | **1,665 / 1,668 = 99.8 %** |

Distribution of the CC tail (the shape matters more than the max):

| Band | Functions | Note |
|---|---:|---|
| CC ≥ 20 | **3** | `_normalized` 28, `wait_page.execute` 25, `history_query._item` 22 |
| CC 16–19 | **12** | the round-3 design queue, unchanged |
| CC 11–15 | **48** | broad low-grade legacy |
| CC > 10 total | **63** | round 2: 64 |

Current hotspots (unchanged from round 2 — **none fixed, none worsened**):

| Location | CC | cognitive | nest | LOC | params |
|---|---:|---:|---:|---:|---:|
| `stores/label_state.py:74` `_normalized` | **28** | 25 | 3 | 50 | 0 |
| `actions/wait_page.py:40` `execute` | 25 | **40** | 3 | 92 | 3 |
| `backend/history_query.py:236` `_item` | 22 | 22 | 2 | 34 | 1 |
| `backend/tab_matcher.py:70` `score_tab` | 20 | 26 | 3 | 36 | 3 |
| `actions/cancellation.py:119` `await_with_stop` | 19 | 35 | **5** | 75 | 4 |
| `services/layout_service.py:42` `normalize_grid_tree` | 19 | 20 | 2 | 36 | 2 |
| `stores/migration.py:39` `migrate_legacy_config` | 19 | 14 | 2 | 79 | 2 |
| `services/history/mutate.py:102` `_merge_legacy_queue` | 18 | 17 | 2 | 22 | 1 |
| `services/run/error_recovery.py:127` `_execute_for_user` | 18 | 26 | 3 | 67 | 2 |
| `stores/history_repo_identity.py:262` `_same_conversation` | 18 | 12 | 1 | 23 | 6 |

Nesting > 4 — the same three sites as round 2:
`bridge/collector_bridge.py:97 collector_command` (**6**, CC 9),
`actions/cancellation.py:119 await_with_stop` (**5**, CC 19),
`backend/cdp_client.py:187 fetch_tabs` (**5**, CC 5).

**Score for Part 1: 96.2 % of functions inside the CC gate, 90.5 % inside *all
five* function gates together** (1,509 / 1,668 clean; 159 offenders, of which
19 break ≥ 3 gates at once). The offenders are all pre-existing legacy.

---

## PART 2 — Size & volume metrics

| Metric | Threshold | Result |
|---|---:|---|
| Function physical LOC | ≤ 20–30 | mean **10.30**, max **122**, **74** over 30 (4.4 %), **222** over 20 |
| Class physical LOC | ≤ 200–300 | mean **80.94**, max **504**, **11** over 300, 36 over 150 |
| Parameters per function | ≤ 3–4 | mean **1.39**, max **20**, **70** over 4 (4.2 %), 106 over 3 |
| Direct methods per class | ≤ 10–15 | mean **6.87**, max **44**, **24** over 15, 44 over 10 |
| Module volume | — | **24,934** physical LOC, **17,509** Radon SLOC, **20,559** nonblank/non-comment |

Per-package volume:

| Package | files | physical LOC | SLOC | mean MI |
|---|---:|---:|---:|---:|
| services | 31 | 6,879 | 5,183 | **49.18** |
| stores | 35 | 6,462 | 4,226 | 63.00 |
| backend | 30 | 5,848 | 4,040 | 71.94 |
| bridge | 12 | 2,540 | 1,962 | 54.82 |
| actions | 23 | 2,437 | 1,601 | 80.52 |
| core | 5 | 481 | 254 | **86.99** |
| app | 4 | 238 | 205 | 71.32 |
| main.py | 1 | 49 | 38 | 60.28 |

Largest classes (god-class candidates — LOC ≤ 300 and ≤ 15 methods is the gate):

| Class | LOC | methods | LCOM\* |
|---|---:|---:|---:|
| `backend/scroll_parser.py:168 ScrollParser` | 504 | 36 | 0.871 |
| `services/collector_service.py:76 Collector` | 503 | 36 | 0.925 |
| `bridge/history_bridge.py:43 HistoryBridge` | 486 | 31 | 0.873 |
| `services/undo_service.py:120 UndoService` | 444 | 26 | 0.907 |
| `stores/history_repo_lifecycle.py:23 PersonLifecycle` | 368 | 18 | — |
| `stores/history_schema_repair.py:35 SchemaMigrator` | 363 | 21 | — |
| `stores/history_repo_append.py:26 AppendPlanner` | 341 | 18 | — |
| `backend/history_query.py:215 HistoryQuery` | 340 | 14 | 0.744 |
| `stores/media_fetch.py:113 MediaFetcher` | 333 | 15 | — |
| `bridge/stack_bridge.py:23 StackBridge` | 308 | 31 | 0.893 |
| `actions/scroll_parse.py:35 ScrollParse` | 306 | 14 | — |

Method-count extremes are mostly facades: `stores/history_repo.py HistoryRepo`
**44 methods / 225 LOC** and `stores/media_store.py MediaStore` 33/215 — small
methods delegating to collaborators, which the class-LOC gate tolerates and the
method-count gate does not. Longest function is still
`backend/dom_probe.py:39 build_probe` (122 LOC, **CC 7**) — exempt under
RULE 16 §1.5 (embedded JS payload); do not split it to satisfy a line count.
Widest signature is still `actions/scroll_parse.py:40 __init__` (20 params,
legacy block constructor).

---

## PART 3 — Coupling & cohesion metrics

### 3.1 Module level (internal imports only, as in prior rounds)

Most depended-upon (high Ca on shared abstractions is desirable reuse):

| Module | Ca | Ce | I = Ce/(Ca+Ce) |
|---|---:|---:|---:|
| `core.events` | 19 | 0 | **0.000** |
| `backend.cdp_client` | 16 | 0 | **0.000** |
| `actions.base_action` | 13 | 2 | 0.133 |
| `core.result` | 11 | 0 | **0.000** |
| `stores.history_models` | 10 | 0 | **0.000** |
| `actions.base` | 8 | 2 | 0.200 |
| `services.run` | 8 | 5 | 0.385 |
| `stores.json_store` | 7 | 2 | 0.222 |
| `stores.user_memory` | 7 | 1 | 0.125 |
| `backend.dom_probe` | 6 | 0 | **0.000** |

Module instability distribution (141 modules): defined I for 138 (3 isolated
modules have no internal importer *or* importee, so I is undefined, not 0);
mean I **0.552**; **69** modules above 0.5; **32** are pure leaves (I = 1.000,
Ca = 0 — mostly `actions/*` block modules, expected for plugins); **35** have
Ca = 0 and **29** have Ce = 0.

### 3.2 Package level (new this round)

| Package | Ca | Ce | I |
|---|---:|---:|---:|
| `core` | 4 | 0 | **0.000** (stable base — correct) |
| `actions` | 2 | 1 | 0.333 |
| `stores` | 4 | 2 | 0.333 |
| `backend` | 5 | 4 | 0.444 |
| `services` | 3 | 4 | 0.571 |
| `bridge` | 1 | 4 | 0.800 |
| `app` | 0 | 4 | 1.000 (composition root — correct) |
| `main.py` | 0 | 0 | n/a (entrypoint) |

### 3.3 Cohesion + the new structural finding

**LCOM\* (Henderson–Sellers, same frozen definition):** mean **0.652** over
**122** eligible classes (round 1: 0.645 / 118); **92** classes sit at ≥ 0.5.
Rising class count with a near-flat mean means the extracted classes did **not**
become more cohesive by themselves — the delegating facades (`Collector` 0.925,
`RunCoordinator` 0.964, `StackBridge` 0.893) are *method-granular* classes that
share almost no state. Under LCOM that reads as low cohesion; under
"thin coordinator over collaborators" it is intentional. Treat as a review list,
not a defect count.

**New: the package dependency graph is not acyclic — 10 cycles.** Measured from
the static import graph (top-level *and* function-local imports; cycles survive
when only top-level edges are kept, so they are not an artifact of deferred
imports):

```
backend -> services -> actions -> backend        backend -> actions -> backend
backend -> bridge -> services -> actions -> b.   services -> backend -> services
services -> stores -> backend -> services        stores -> backend -> stores
bridge -> backend -> bridge                      bridge -> stores -> backend -> bridge
bridge -> services -> backend -> bridge          backend -> bridge -> services -> …
```

Every cycle routes through **`backend`**, and a meaningful share of the edges
that close them are **compatibility re-export shims**, not real dependencies:

* `backend/bridge.py:9-10` re-exports `bridge.router`/`bridge.context` (shim);
* `backend/action_engine.py:3` re-exports `services.run` (shim, `# noqa: F401`);
* real edges: `actions/{attach_image,click_send,click_user,collect_history}.py →
  backend.cdp_client|visual_click|message_injector`,
  `backend/{visual_click,action_engine}.py → actions.base_action`,
  `stores/media_fetch.py:28 → backend.chat_agent_js`,
  `bridge/history_bridge.py:18 → backend.history_query`,
  `backend/{chat_parser,chat_sync,config_manager}.py → stores.*`.

Consequence: import order is load-bearing (the `# noqa: F401` markers are the
symptom), and `backend` currently behaves as both a lower layer and a peer.
Retiring `backend/bridge.py` + `backend/action_engine.py` re-exports toward
their real modules removes 4 of the 10 cycles without touching behaviour.

---

## PART 4 — Test quality metrics

**Python suite:** 2,545 passed, 0 failed, 3 skipped, 1 deselected
(`test_sash_webengine.py::…::test_grid_in_real_webengine` — aborts in this
headless sandbox), 1 xfailed, 771 subtests passed, 1 warning, 330.37 s.

| Metric | Target | Result | Verdict |
|---|---:|---|---|
| Line / statement coverage | ≥ 80 %, never decrease | **90.44 %** (12,237 / 13,531) | floor **pass**; ratchet **passes by +0.03 pp** vs the recorded 90.41 % |
| Branch coverage | ≥ 75 % | **88.99 %** (2,935 / 3,298; 363 partial) | **pass**, +4.61 pp |
| Mutation score | ≥ 70 % | **94.34 %** — 150 killed / 9 survived / 0 timeout, 1,066 "no tests" excluded per the documented `setup.cfg` convention | **pass, but on one module only** (see below) |
| Test-to-code ratio | ~1:1 | **1.65 : 1** (34,005 test lines / 20,559 prod lines, 164 Python test files) | test volume comfortably exceeds production |
| Absolute uncovered code | lower is better | **1,294** statements, **363** branch destinations (round 1: 1,400 / 556) | improving |

Coverage.py's own combined line+branch figure is **89.25 %** — neither of the two
reported numbers (line **90.44 %**, branch **88.99 %**). Both prior rounds report
the line figure the same way as here: covered ÷ statements.

Per-package, against the round-1 recorded table (round 2 published no split):

| Package | line now | line r1 | branch now | branch r1 | Δ branch |
|---|---:|---:|---:|---:|---:|
| core | 100.00 % | 100.00 % | 91.67 % | 91.67 % | 0 |
| stores | 93.37 % | 93.37 % | 88.61 % | 87.80 % | +0.81 |
| actions | 93.54 % | 95.89 % | 86.67 % | 83.33 % | +3.34 |
| services | 90.11 % | 91.12 % | 89.53 % | 85.35 % | **+4.18** |
| backend | 89.16 % | 89.02 % | 91.35 % | 84.20 % | **+7.15** |
| **bridge** | **85.52 %** | **67.44 %** | **85.09 %** | **48.43 %** | **+36.66** |
| app | 79.69 % | 79.69 % | 85.29 % | 61.76 % | **+23.53** |
| main.py | 97.37 % | 97.37 % | 50.00 % | 50.00 % | 0 |

**This is where your fixes landed.** The round-1 "global success hides the
testing gap: bridge" finding is essentially closed:
`bridge/stack_bridge.py` went from 92/242 statements and 2/32 branches to
**248/248 (100 %) and 34/34 (100 %)**; `bridge/undo_bridge.py` 100 % / 25 of 26
branches; `bridge/router.py` 100 % / 57 of 60; `bridge/db_bridge.py` 87.1 % /
11 of 12.

Remaining coverage floor, by **line** (only **1** file under 60 %, and **no** file
at 0 %; **64 / 141** files are at 100 %, **112 / 141** are ≥ 90 %):

| File | line | missing stmts | branch |
|---|---:|---:|---:|
| `app/lifecycle.py` | 35.8 % (19/53) | 34 | 8/8 |
| `backend/cdp_client.py` | 64.3 % (146/227) | 81 | 44/50 |
| `bridge/history_bridge.py` | 64.8 % (236/364) | 128 | 65/90 |
| `bridge/layout_bridge.py` | 66.3 % (65/98) | 33 | 12/12 |
| `backend/message_injector.py` | 69.8 % (150/215) | 65 | 50/58 |
| `services/db_registry.py` | 70.0 % (112/160) | 48 | 36/46 |
| `services/db_deletion_scan.py` | 70.9 % (83/117) | 34 | 25/30 |
| `backend/chat_text.py` | 73.6 % (39/53) | 14 | 19/24 |

Those **8 files hold 437 of the 1,294 uncovered statements**. Characterising them
with asserting tests (not just executed ones) would put global line coverage at
≈ **93.7 %**; **144** newly covered statements are enough to reach 91.5 % and buy
the ratchet a real margin instead of the current 4-statement cushion.

`actions` is the one package that genuinely lost line coverage (95.89 % → 93.54 %):
concentrated in `actions/cancellation.py` **76.3 %** (27 missing) and
`actions/collect_history.py` **86.0 %** (22 missing) — the shared stop core and the
collect block, i.e. the two highest-risk paths for the next refactor round.

**Mutation score (new).** `setup.cfg` pins mutmut to `source_paths=backend/history_query.py`
with a 3-file test selection (`test_person_item`, `test_person_page_request`,
`test_userdb_sort_query`); run in ~3 min at 6.85 mutations/s over 1,225 mutants.

```
🎉 killed 150   🙁 survived 9   ⏰ timeout 0   🫥 no-tests 1,066
score = 150 / (150 + 9) = 94.34 %   (12.24 % if "no tests" were counted as escapes)
survivors: _like_escape ×2, HistoryQuery._clamp ×2, HistoryQuery._my_nicks ×1,
           HistoryQuery.list_persons ×4
```

Reading it honestly: on the slice the harness can reach, the tests are strong —
94.34 % ≫ the 70 % target. But the harness reaches **13.3 %** of the module's
mutants (159 of 1,225): the 1,066 "no tests" mutants live in functions the
narrow selection never imports, so this is **not** a project-wide mutation
score, and `list_persons` keeping 4 survivors inside a file that is 96.1 %
line-covered is
exactly the "executed ≠ asserted" gap RULE 16 §3 warns about. `page()`/`_search()`
boundary values and the `_clamp` off-by-one space are the concrete gaps.

**JS:** 22 entrypoints under `tests/test_*.js`, all pass (round 1 had 20 with
1 stale failure on the `registerObject("bridge")` source-location assertion —
that test is now updated/green). No JS line/branch/mutation coverage is
collected; the 22 frontend JS files (8,441 physical LOC) and JS embedded in
Python string builders remain outside every coverage denominator here.

**Environment:** real PySide6 6.11.2 imports with `tools/build_stubs.py`-generated
headless shims, `QT_QPA_PLATFORM=offscreen`. Not real GUI/GL validation. The
single warning is still the unawaited `Collector.handle_push` coroutine from
`test_push_binding_ignores_other_bindings` (`services/history/runtime.py:63`) —
open since round 1, unaddressed.

---

## PART 5 — Code smell metrics

| Smell | Method | Result | vs round 2 |
|---|---|---|---|
| Duplicated code | `tools/metrics/clone_scan.py` (exact-AST statement windows ≥ 6 lines, cross-file) | **12 groups / 90 unique physical lines = 0.36 %** of production LOC | **flat** — no new clone introduced |
| Duplicated code (lenient) | pylint `R0801`, `--min-similarity-lines=6` | **1** report (the `BlockField(...)` + `__init__` block in the find/click actions) | — (new comparator) |
| Dead code | Vulture 2.16, ≥ 90 % confidence | **7**: unused import `Iterator` (`actions/registry.py:18`); unused `exc_type`/`tb` (`backend/cdp_client.py:35`); unused `scroll_parser` (`services/run/coordinator.py:60`); 3 unused `coordinator` hook args (`services/run/hooks.py:68,71,74`) | **flat**, same set |
| Dead code (loose) | Vulture at ≥ 60 % | 210 reports — dominated by QWebChannel slots and dynamically reached names; **not** a defect count | — |
| Long methods | > 30 physical LOC | **74**; of these only 26 also break a complexity gate | −1 |
| God classes | > 300 LOC or > 15 methods | **27 / 197** classes (11 by size, 24 by method count) | flat |
| Feature envy | new conservative heuristic (`self.x` vs foreign-object distinct attribute touches, ≥ 3 foreign attrs, target not constructed in-function) | **60 candidate functions** | **new** |

Exact-AST clone top groups (identical lists to round 2, so the persisted
scanner is stable): 15-line block shared by `actions/click_back.py:20` /
`actions/click_main_tab.py:19`; 9-line block across `stores/labels_file_store.py:10`,
`stores/session_store.py:14`, `stores/settings_store.py:9`; 7-line pairs in
`services/history/mutate.py`↔`services/undo_service.py`,
`services/run/coordinator.py`↔`services/run/progress.py`,
`backend/media_handler.py`↔`backend/message_injector.py`, and 4 bridge pairs
(6–7 lines). Caveat that has not changed: the scanner finds **exact copies
only** — renamed or restructured duplication is invisible to it, and JS is out
of scope. 0.36 % is not "99.64 % DRY".

Feature-envy candidates, strongest 8 (heuristic — DTO/projector functions are
expected here, so treat as a review list):
`services/db_deletion_scan.py:191 _build_plan` (0 self vs 12 `st.*`),
`services/people_service.py:25 people_row` (0 vs 11 `u.*`),
`stores/history_repo_append.py:170 _insert_message` (1 vs 9 `rec.*`),
`services/collector_service.py:325 _remember_partner` (3 vs 8 `existing.*`),
`services/db_deletion_flow.py:98 raise_refusal` (0 vs 8 `st.*`),
`services/db_deletion_flow.py:458 _success_outcome`, `:486 _cancel_reconcile`,
`backend/chat_sync.py:412 read` (5 vs 6 `s.*`).
Three of the ten strongest live in `services/db_deletion_flow.py` — further
evidence for the module split already proposed in
`docs/CC_REMAINING_TAIL_DESIGN_2026-09-10.md` §1.3.

---

## PART 6 — Maintainability metrics

**Maintainability Index (Radon `mi_visit(..., multi=True)`, per file, unweighted
mean over 141 files): 65.09** (round 2: 65.06, round 1: 65.42). Median 61.54;
2 files below 20; none negative. Radon's scale is not the classic MI band set —
use it for *relative* movement only.

Mean MI per package: `services` **49.18** and `bridge` **54.82** drag the project;
`core` 86.99 and `actions` 80.52 are the healthy ends.

Lowest files: `backend/chat_sync.py` 11.86 (771 LOC), `services/history/mutate.py`
19.02, `services/db_deletion.py` 20.54 (665 LOC), `services/undo_service.py`
21.45, `bridge/history_bridge.py` 23.72, `services/history/query.py` 27.71,
`services/collector_service.py` 28.28, `backend/scroll_parser.py` 28.74,
`services/run/progress.py` 29.74, `services/db_deletion_flow.py` 31.50,
`stores/media_fetch.py` 31.58, `services/run/hooks.py` 32.22.

**Technical Debt Ratio — first modelled estimate (was "unavailable").** TDR =
interest / (interest + principal). Explicit model, so the number is auditable and
re-runnable; it is an **estimate**, not a measurement:

* **Principal** (replace-from-scratch cost) = 17,509 SLOC × 10 min/SLOC = **2,918 h**.
* **Interest — structural:** 19 functions breaking ≥ 3 gates × 3.0 h +
  32 breaking 2 × 1.5 h + 108 breaking 1 × 0.75 h + 27 oversized classes × 2.0 h
  + 12 clone groups × 0.5 h + 7 vulture findings × 0.25 h = **247.8 h**.
* **Interest — tests:** (1,294 missing statements + 363 partial branches) × 4 min
  = **110.5 h**.

| Variant | TDR | Interpretation |
|---|---:|---|
| structural only | **7.8 %** | inside the usual 5–10 % "attention" band |
| structural + test debt | **10.9 %** | at the "danger" boundary; the test half is what pushes it over |

The 4 min/finding and the 10 min/SLOC anchors are the two soft spots: halving
the remediation rates moves TDR to ≈ 5.4 %, doubling to ≈ 21 %. Track the
*direction* of the offender counts (159 now) rather than the absolute ratio.

**Code churn: still unavailable.** One commit of history in this checkout; a
root-commit diff is not a churn signal. To enable it, run future audits against
a full clone — `git log --numstat --format=%h -- <path>` per file, then flag
"high churn × low coverage" as the refactor priority list. (Proxy this round:
the 9 files in §4 carry both the least coverage and the most recent edit
activity per the round-2/3 design docs.)

**Bug density: still unavailable as defined** (confirmed defects / KLOC needs a
defect ledger and a period). Reported defect-tracker-free signals instead:
**0 failing tests**, 1 xfail, 3 skips, 1 environment deselect, 1 open runtime
warning, and the round-2 §6 open-problem backlog — **7 items, 3 now closed**:

| Round-2 §6 item | Now |
|---|---|
| 1. CC 16–28 legacy tail (12 functions ≥ 16) | **open** (15 at ≥ 16, max 28) |
| 2. Three nesting > 4 sites | **open** (still the same three) |
| 3. `services/db_deletion.py` 665 LOC / MI 20.54 split | **open** (unchanged 665 / 20.54) |
| 4. `RunCoordinator` 181/17 and `DbRegistry` 223/14 over class gates | **open** (identical) |
| 5. Two frozen wide signatures (`classify_candidate` 7, `plan_deletion` 9) | **open** (not worsened; both now CC 5 / CC 4) |
| 6. Coverage pockets in round-2 units + untested raw facade | **partly open**: `cycle_loop.py` 82.9 % (6 missing), `run_lifecycle.py` 92.7 % (6 missing), `db_registry.py` 70.0 % — `deletion_inventory_sources` still unexercised by tests |
| 7. bridge coverage / stale JS test / unawaited coroutine | **bridge closed** (67.4 → 85.5 % line, 48.4 → 85.1 % branch), **JS closed** (22/22), **warning still open** |

---

## Structured phases — recommended order from these numbers

1. **Give the coverage ratchet a real margin (cheapest win available).**
   437 of the 1,294 uncovered statements sit in 8 files under 75 % line, top
   being `bridge/history_bridge.py` (128) and `backend/cdp_client.py` (81).
   Covering 144 of them lifts global line coverage to ≈ 91.5 % — currently the
   90.41 % baseline is protected by only ≈ 4 statements.
2. **Kill the mutation survivors before touching the code they guard.**
   4 in `HistoryQuery.list_persons`, 2 in `_like_escape`, 2 in `_clamp`, 1 in
   `_my_nicks` — table/property tests on boundaries (page clamping, `%`/`_`
   escaping, nick matching). Then widen `setup.cfg` `source_paths` to the next
   pure module (`stores/label_state.py`, `backend/tab_matcher.py`) so the
   mutation metric stops covering 13 % of one file.
3. **Then the CC tail, in the designed order.** The 12-function queue in
   `docs/CC_REMAINING_TAIL_DESIGN_2026-09-10.md` §1.1 is still valid verbatim;
   start with the pure ones (`label_state._normalized` 28, `tab_matcher.score_tab`
   20, `media_layout.slugify_nick`) where mutation coverage already exists to
   prove equivalence, and leave `actions/cancellation.py await_with_stop`
   (CC 19, nest 5, 75.3 % covered) until its 27 missing statements are
   characterised first.
4. **Structural hygiene with measurable payoff:** retire the two `backend/*`
   re-export shims to cut 4 of 10 package cycles; split `services/db_deletion.py`
   (665 LOC, MI 20.54) along the four responsibilities already named; add the
   missing tests for `deletion_inventory_sources` or delete the facade.
5. **Fix the one open runtime warning** (unawaited `handle_push` coroutine in
   `services/history/runtime.py:63`) — it is both a test-hygiene and a
   potential production-lifecycle bug, and it has now survived three rounds.
6. **Make debt trends measurable:** run the next audit from a full-history clone
   (unlocks code churn), and keep `tools/metrics/current_audit.py` +
   `clone_scan.py` as the frozen scanners so every report stays comparable.

Do **not**: split `dom_probe.build_probe` (122 LOC, §1.5 exempt), collapse the
frozen wide signatures without a facade-versioning decision, or chase LCOM\* ≥ 0.5
on deliberate delegation facades (`HistoryRepo` 44 methods / 225 LOC).

---

## Reproduction

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt      # + PySide6 via requirements.txt
.venv/bin/python tools/build_stubs.py .venv /tmp/stublibs   # headless Qt shims

# complexity / size / coupling / MI / LCOM / clones / test-code ratio
.venv/bin/python tools/metrics/current_audit.py > /home/user/analysis/audit_round3.json
# duplication (tool of record, comparable with round 2)
.venv/bin/python tools/metrics/clone_scan.py
# lenient duplication
.venv/bin/python -m pylint --disable=all --enable=R0801 --min-similarity-lines=6 \
  core actions backend bridge services stores app main.py
# dead code
.venv/bin/vulture core actions backend bridge services stores app main.py --min-confidence 90
# suite + branch coverage
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage json -o /home/user/analysis/coverage_round3.json
# mutation score (scope configured in setup.cfg)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut run --max-children 8
.venv/bin/mutmut results --all True
# JS
for f in tests/test_*.js; do node "$f" || echo "FAIL $f"; done
```

Raw evidence (outside the checkout, deliberately not committed):
`/home/user/analysis/audit_round3.json`, `coverage_round3.json`, `.coverage`,
`pytest_round3.txt`, `mutmut_run.txt`, plus the aggregation helpers
`summarize.py` / `envy.py` used for the §1/§5 tables. No production or test file
was modified for this audit — `git status` is clean apart from this report.
