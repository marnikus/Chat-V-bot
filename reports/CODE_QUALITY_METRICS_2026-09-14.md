# Code quality audit — 2026-09-14

Snapshot: `5197ce0` ("upd"), branch `arena/01a09a119-chat-v-bot`. **No production
code was changed to produce this audit**; every number below was re-measured
from the tree with the commands in **Reproduction**, and the raw artifacts were
written **outside** the checkout (`/tmp/audit_h.json`, `/tmp/coverage_h.json`,
`/tmp/js_cov_h.json`, `/tmp/mutmut_results.txt`) because coverage and mutmut
output are not gitignored.

Organised against the six requested categories: complexity, size,
coupling/cohesion, tests, smells, maintainability.

## Executive summary

**Complexity is still solved, and the test suite got stronger. Size is still the
whole debt — and this audit found *where* it lives: outside the gate.**

Across 2,268 production functions there is **not one** above cyclomatic
complexity 10, **not one** above cognitive complexity 15, and **not one** nested
deeper than 4. The maximum values are exactly 10 / 15 / 4 — at the ceiling, never
past it. That category has now been clean for three consecutive audits.

What remains is mass, and the concentration is the finding:

* **23 files over 300 lines** (4 over 500) hold **28.4%** of all production LOC;
* **36 classes over 150 LOC**, of which **6 are over 300**;
* **39 functions over 30 LOC** and **195 over 20** — the RULE 18 ideal band is
  4–20, and 62.5% of functions sit inside it;
* the worst maintainability index in the tree is **24.9** (`bridge/history_bridge.py`),
  up from 11.1 on 2026-09-12 — the floor moved 2.1×, but 16 files are still
  below the MI 40 line.

And the structural finding that decides Round H: **the RULE 16 gate enforces
164 named functions in 20 files — 9.6% of the files, 11.9% of the LOC.** Every
single one of the 39 long functions, 33 of the 36 oversized classes, 21 of the
23 oversized files and all 11 wide-parameter functions sit **outside** it. The
class-size loop added in Round F/G runs `for rel in sorted({k[0] for k in OWNED})`
— classes in the 20 touched files. On top of that, `RATCHET` is a *ceiling*, not
a floor: `HistoryQuery` measures 310 LOC against a frozen cap of 362, so the
worst class in the worst file may still grow 17% with the gate green.

Test health is the strongest it has ever been: **3,172 passed / 0 failed**,
**902 subtests**, **92.64% line**, **88.03% branch**, **99.37% mutation score**
(158/159 reachable), test-to-code ratio **1 : 1.57**, and the JavaScript half is
measured for the second time at **82.8%** with 29/29 Node entrypoints green.
The remaining test debt is *local and named*, not diffuse: 1,250 uncovered
statements, concentrated in five modules, plus 6 JS files no test loads.

### Before → now

Previous columns: `reports/CODE_QUALITY_METRICS_2026-09-12.md` (snapshot
`e4ef002`, Round F start) and the Round G close-out recorded in
`docs/archive/2026-09-13-round-g-write-gate/G7_BACKLOG_DESIGN_2026-09-13.md` §6.
"not recorded" means the earlier audit did not publish that number.

| Metric | 2026-09-12 | Round G close (09-13) | **2026-09-14** | Direction |
|---|---:|---:|---:|---|
| Python test results | 2,710 passed | 2,828 passed | **3,172 passed / 0 failed** | +344 since G7 |
| Python subtests | 777 | 898 | **902** | ✅ |
| Python line coverage | 90.41% | 91.38% | **92.64%** | +1.26 pp since G7 |
| Python branch coverage | 86.30% | 87.51% | **88.03%** | +0.52 pp since G7 |
| Mutation score (configured job) | 94.34% (9 survivors) | 99.37% (1 survivor) | **99.37%** (1 survivor) | ✅ held |
| Max Radon CC | 10 | 10 | **10** | ✅ none above |
| Functions above CC 10 | 0 | 0 | **0 / 2,268** | ✅ |
| Max cognitive complexity | 17 (2 functions) | 15 (0 above) | **15, 0 above** | ✅ closed in G6 |
| Max nesting depth | 4 | 4 | **4, 0 above** | ✅ |
| Production files | 159 | not recorded | **208** | +49 modules |
| Production functions | 1,997 | not recorded | **2,268** | +13.6% |
| Production nonblank/noncomment | 23,136 | not recorded | **26,333** | +13.8% |
| Test nonblank/noncomment | 36,178 | not recorded | **41,268** | ratio 1 : 1.57 |
| Mean maintainability index | 64.85 | not recorded | **68.05** | +3.20 |
| Minimum maintainability index | 11.1 | not recorded | **24.9** | 2.2× better |
| Files below MI 40 | 22 | not recorded | **16** | ✅ halved |
| Files > 500 lines | 10 | 4 | **4** | ✅ held |
| Classes > 150 LOC | 38 | 36 | **36** | held, ungated |
| Functions > 30 LOC | 42 | 39 | **39** | held, ungated |
| Functions > 4 params | 51 (then 18) | 11 (floor) | **11** | ✅ at the RULE-3 floor |
| JS test entrypoints | 26 / 26 | 28 / 28 | **29 / 29 pass** | ✅ |
| JS files attributed / coverage | not measured | 24 files, 80.18% | **30 files, 82.8%** | ✅ +2.6 pp |
| Gate blast radius | whitelist | whitelist | **20 files = 9.6%, 11.9% of LOC** | ❌ **the Round H problem** |

The delta since the Round G close is the AI Bot Chat surface landing in the tree
(`ui/js/bot-*.js`, `dark-select.js`, `services/bot_*.py`, `bridge/bot_*.py`) plus
its tests: +6 attributed JS files, +1,786 JS lines, +344 Python tests, +1,032
production statements on the coverage denominator, and not a single regression in
the complexity ceiling. Coverage went **up** while the denominator grew.

## 1. Complexity and size against your thresholds

Scope: all 208 production Python files under `core`, `actions`, `backend`,
`bridge`, `services`, `stores`, `app`, plus `main.py`. Excludes tests, `tools/`,
vendored assets, frontend JavaScript and generated caches.

### 1a. Complexity

| Measure | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Cyclomatic complexity (max) | ≤ 10 | **10** | ✅ at the ceiling, 0 above |
| Functions with CC > 10 | 0 | **0 / 2,268** | ✅ closed (4th audit running) |
| Mean CC | — | 3.09 → **2.98** (median 2, p95 8) | healthy |
| Cognitive complexity (max) | ≤ 15 | **15** | ✅ 0 above (the two 17s are gone) |
| Nesting depth (max) | ≤ 3–4 | **4** | ✅ at the loose bound, 0 above |
| Functions with nesting > 4 | 0 | **0** | ✅ |
| Radon rank distribution | — | A 1,904 · B 328 · C or worse **0** | ✅ |

Mean cognitive complexity is 2.02 with p95 of 8: the distribution is flat, not
merely capped. The 26 functions sitting exactly at CC 10 are the ones to watch —
they have no headroom at all; a new `and`/`or` in any of them fails the gate.
The largest of them, by file: `actions/cancellation.py::sleep_with_stop` (34 LOC,
CC 10), `actions/type_message.py::execute` (23 LOC, CC 10, cognitive 15 — the
single densest function in the tree), `backend/person_filter.py::check`
(cognitive 14), `backend/scroll_parser_judge.py::consume_batch` (cognitive 15).

### 1b. Size — this is where the debt lives

| Measure | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Function length (max) | ≤ 20–30 LOC | **107** | ⚠️ `backend/dom_probe.py::build_probe`, embedded-JS payload |
| Mean / median function LOC | — | **9.19 / 7** | ✅ |
| Functions in the RULE 18 band (4–20) | aim here | **1,418 (62.5%)** | ✅ median 7 |
| Functions > 30 LOC | few | **39 (1.7%)** | ⚠️ tail, **0 gated** |
| Functions > 20 LOC | few | **195 (8.6%)** | ⚠️ tail |
| Class size (max) | ≤ 200–300 LOC | **467** | ❌ `HistoryBridge` |
| Classes > 300 LOC | 0 | **6** | ❌ |
| Classes > 150 LOC (the gate line) | 0 | **36 (12.9%)** | ❌ |
| Parameters (max) | ≤ 3–4 | **20** | ❌ RULE 3 block wire, override recorded |
| Functions > 4 params | few | **11** | ⚠️ at the documented floor |
| Methods per class (max) | ≤ 10–15 | **44** | ⚠️ `HistoryRepo`, a deliberate facade |
| Classes > 15 methods | 0 | **24 (8.6%)** | ❌ |
| File size (max) | ≤ ~300 | **601** | ❌ 2× |
| Files > 500 lines | 0 | **4** | ❌ |
| Files > 300 lines | few | **23 (11.1%)** | ❌ 28.4% of production LOC |
| Files in the 150–300 band | aim here | **68** | ✅ |
| Files ≤ 150 | fine | **117** | ✅ |

**Mass concentration.** The distribution is not a long smooth tail; it is a
small number of files carrying a large fraction of the code:

| Cut | Files | LOC held | Share of production LOC |
|---|---:|---:|---:|
| > 500 | 4 | 2,170 | 6.7% |
| > 400 | 11 | 5,327 | 16.3% |
| > 300 | 23 | 9,268 | **28.4%** |
| > 250 | 41 | 14,298 | 43.9% |

**Every production file over 300 lines** (SLOC in brackets, `NOTE` = carries an
`ideal-size:` reason; every one of these is outside any gate):

| Lines | SLOC | MI | Gate | File |
|---:|---:|---:|---|---|
| 601 | 417 | 35.3 | NOTE | `backend/history_query.py` |
| 544 | 450 | **24.9** | NOTE | `bridge/history_bridge.py` |
| 514 | 371 | 54.9 | NOTE | `backend/dom_highlight.py` |
| 511 | 319 | 40.9 | NOTE (stale, says 507) | `backend/config_manager.py` |
| 486 | 324 | 44.2 | — | `bridge/router.py` |
| 474 | 301 | 46.1 | — | `backend/media_handler.py` |
| 464 | 320 | 31.5 | — | `stores/media_fetch.py` |
| 441 | 319 | 37.7 | — | `stores/history_repo_lifecycle.py` |
| 441 | 301 | 41.8 | — | `stores/history_schema_repair.py` |
| 426 | 245 | 40.9 | — | `backend/chat_parser.py` |
| 425 | 308 | 33.0 | — | `services/collector_tick.py` |
| 366 | 256 | 43.0 | — | `stores/history_repo_append.py` |
| 365 | 233 | 44.1 | — | `stores/history_repo_identity.py` |
| 333 | 246 | 39.7 | — | `bridge/stack_bridge_parts.py` |
| 332 | 247 | 37.5 | — | `bridge/file_bridge.py` |
| 331 | 244 | 36.7 | — | `backend/cdp_client.py` |
| 330 | 168 | 53.9 | — | `actions/base.py` |
| 328 | 228 | 41.1 | — | `services/db_lifecycle.py` |
| 326 | 251 | 30.6 | NOTE | `services/window_preset_service.py` |
| 314 | 236 | 31.0 | NOTE | `services/run/progress.py` |
| 312 | 212 | 43.8 | — | `services/preset_io.py` |
| 302 | 185 | 55.3 | — | `stores/history_repo_media.py` |
| 302 | 212 | 43.8 | — | `services/db_registry.py` |

**16 of the 23 carry no `ideal-size:` reason** — the §18.5 escape hatch is
declared-and-reported territory, and two thirds of the over-ideal files never
used it.

**Biggest classes** (LOC / direct methods / LCOM\*):

| LOC | Methods | LCOM\* | Class | Reading |
|---:|---:|---:|---|---|
| 467 | 31 (44 incl. nested) | 0.86 | `bridge/history_bridge.py::HistoryBridge` | worst file, at its ratchet cap |
| 407 | 25 | **0.12** | `stores/history_schema_repair.py::SchemaMigrator` | long but cohesive — extract helpers |
| 375 | 19 | **0.06** | `stores/history_repo_lifecycle.py::PersonLifecycle` | long but cohesive |
| 325 | 18 | **0.18** | `stores/history_repo_append.py::AppendPlanner` | long but cohesive |
| 310 | 14 | 0.74 | `backend/history_query.py::HistoryQuery` | ratcheted, 52 lines of headroom |
| 306 | 15 | 0.21 | `stores/media_fetch.py::MediaFetcher` | long but cohesive |
| 276 | 22 | 0.88 | `services/db_lifecycle.py::DbLifecycle` | incoherent — decompose |
| 227 | 22 | **0.94** | `services/run/progress.py::RunQueueMixin` | incoherent |
| 216 | 40 | **0.95** | `services/collector_service.py::Collector` | incoherent |

The LCOM split is the actionable part: `SchemaMigrator`, `PersonLifecycle`,
`AppendPlanner` and `MediaFetcher` are single-responsibility units that happen to
be long (RULE 19 §19.5 "long-and-flat" → extract per phase), while `DbLifecycle`,
`RunQueueMixin`, `Collector` and `HistoryBridge` are large *and* incoherent and
need decomposition by responsibility first.

**Most methods on one class:** `HistoryRepo` 44 (225 LOC, one-line delegations
over the `history_repo_*` family — the correct facade shape, not a defect),
`Collector` 40, `LabelStore` 38, `MediaStore` 33, `HistoryBridge` 31 (44 by the
gate's nested-inclusive count), `HistoryDB` 30, `UndoService` 28, `SchemaMigrator`
25.

**Longest functions:** `backend/dom_probe.py::build_probe` 107 (embedded JS, §16.1.5
exempt), `stores/history_db.py::init` 54, `backend/history_query.py::page` 53,
`stores/history_repo_append.py::append` 50, `backend/history_query.py::_search`
49, `actions/scroll_parse.py::config_schema` 44 (data, not logic),
`bridge/history_bridge.py::history_delete_person` 44,
`services/db_lifecycle.py::_clean_unlocked` 42,
`stores/history_repo_append.py::_write_rows` / `_prepend` 42.

**Widest parameter lists** (RULE 3 block constructors keep their wire signature —
§16.4 overrides are recorded for them):

| Params | LOC | Function |
|---:|---:|---|
| 20 | 30 | `actions/scroll_parse.py::__init__` |
| 13 | 29 | `actions/click_user.py::__init__` |
| 11 | 14 | `actions/custom_find.py::__init__` |
| 9 | 13 | `actions/attach_image.py::__init__` |
| 9 | 14 | `actions/collect_history.py::__init__` |
| 8 | 28 | `bridge/router.py::__init__` |
| 7 | 10 | `actions/click_back.py`, `actions/click_main_tab.py`, `actions/click_send.py`, `actions/type_message.py` (5) |
| 5 | 25 | `backend/chat_sync.py::run_sync` |

### 1c. What the gate actually measures

This is the audit's most consequential finding, so it is stated as its own
section rather than a footnote.

| Enforcement | Scope | Share of tree |
|---|---|---|
| Function limits (LOC / params / CC / cognitive / nesting) | **164 named functions in 20 files** (`OWNED`) | 7.2% of 2,268 functions |
| Class limits (150 LOC / 15 methods) | classes in those 20 files, minus 3 ratcheted | **21 of 279 classes (7.5%)** |
| File size | not measured by the gate at all | 0% |
| `RATCHET` (frozen legacy) | 3 classes | ceiling, **not floor** |
| Blast radius | 20 files | **9.6% of files · 11.9% of production LOC** |

Consequences, each verifiable in the tables above:

1. **39 / 39 long functions are ungated.** Not one function over 30 LOC appears
   in `OWNED`.
2. **33 / 36 oversized classes are ungated.** The three inside owned files are
   all `RATCHET`-exempt.
3. **21 / 23 oversized files are ungated** (`backend/history_query.py` and
   `bridge/history_bridge.py` are named — but only their functions, and only the
   listed ones).
4. **11 / 11 wide-parameter functions are ungated** (they are `actions/` blocks
   whose signature is the preset wire format, RULE 3 — a legitimate constraint,
   but nothing enforces it *as* a constraint after the fact).
5. **`RATCHET` permits growth up to the pre-refactor size.** `HistoryQuery` is
   measured at 310 LOC with a cap of 362: the class can grow 52 lines (+17%) and
   stay green. `HistoryBridge` (467) and `ScrollRunPart` (197) sit exactly at
   their caps and cannot grow — a two-sided ratchet would say "may shrink, must
   not grow" for all three.

The gate is green and honest about what it checks (`--with-clones`: 0 new groups,
0 stale baseline entries, no stale overrides). The gap is breadth, not integrity.

## 2. Coupling and cohesion

### Stability (Ca = used-by, Ce = depends-on, I = Ce/(Ca+Ce))

**Most depended-upon — the stable abstractions (I ≈ 0):**

| Module | Ca | Ce | I |
|---|---:|---:|---:|
| `core.events` | 27 | 0 | 0.00 |
| `backend.cdp_client` | 21 | 0 | 0.00 |
| `core.result` | 17 | 0 | 0.00 |
| `services` (package) | 14 | 0 | 0.00 |
| `actions.base_action` | 13 | 2 | 0.13 |
| `stores.history_models` | 13 | 0 | 0.00 |
| `actions.speed` | 10 | 0 | 0.00 |
| `actions.base` | 9 | 3 | 0.25 |
| `services.run` | 9 | 6 | 0.40 |

**50 modules sit at I ≥ 0.77** and every one inspected is a composition root,
bridge or coordinator — i.e. something whose job is to depend on many things and
be depended on by almost nothing. **The dependency graph still does not need
repair.** One coupling *risk* does stand out now that coverage is measured:
`backend/cdp_client` is the tree's second most-depended-upon module (Ca 21) and
is covered at **63.14%** — the single highest-leverage untested module in the
repository.

### Cohesion (LCOM\*)

Measured over 170 classes with ≥ 2 methods and ≥ 1 field: **mean 0.594**, with
**114 (67.1%) at or above 0.5** — slightly better than the 0.650/72.7% of
2026-09-12.

Read it as a triage signal, not a gate (the 2026-09-12 audit's caveat still
holds: `PersonPageRequest` scores ~1.00 precisely because it is the parameter
object the rules recommend). Filtered to classes that hold mutable state and
implement behaviour, the genuine cohesion problems are:

| LCOM\* | Methods | Class |
|---:|---:|---|
| **0.97** | 17 | `services/run/coordinator.py::RunCoordinator` |
| **0.95** | 40 | `services/collector_service.py::Collector` |
| **0.95** | 28 | `services/undo_service.py::UndoService` |
| **0.94** | 22 | `services/run/progress.py::RunQueueMixin` |
| **0.93** | 33 | `stores/media_store.py::MediaStore` |
| **0.93** | 14 | `actions/click_user.py::ClickUser` |
| **0.91** | 21 | `backend/cdp_client.py::CDPClient` |
| **0.88** | 22 | `services/db_lifecycle.py::DbLifecycle` |
| 0.86 | 31 | `bridge/history_bridge.py::HistoryBridge` |
| 0.86 | 30 | `stores/history_db.py::HistoryDB` |

Healthy by contrast: `SchemaMigrator` 0.12, `PersonLifecycle` 0.06,
`AppendPlanner` 0.18, `MediaFetcher` 0.21.

**Feature envy / boundary smell.** `services/db_registry.py:289` still calls
`db_deletion._append_db_files(...)` — a private name reached across a module
boundary. It is now *documented* (`services/db_deletion.py` carries an explicit
re-export shim for that call site), so it is a recorded smell rather than an
unnoticed one; it becomes public-or-removed when `db_registry` is next touched.

## 3. Test quality

| Measure | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Python tests passing | all | **3,172 passed / 0 failed** | ✅ |
| Skipped / deselected / xfailed | — | 2 / 1 / 1 | documented below |
| Subtests | — | **902 passed** | ✅ |
| Line coverage | ≥ 80% | **92.64%** (15,745 / 16,995) | ✅ +12.6 pp |
| Branch coverage | ≥ 75% | **88.03%** (3,514 / 3,992) | ✅ +13.0 pp |
| Mutation score | ≥ 70% | **99.37%** (158 / 159 reachable) | ✅ +29 pp |
| Test : production ratio | ~1 : 1 | **1 : 1.57** | ✅ exceeds |
| JS test entrypoints | all pass | **29 / 29** | ✅ |
| JS measured coverage | (no floor exists) | **82.8%** (8,822 / 10,656 executable) | ✅ measurement |

**Skips.** 1 deselected is `tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine`
(needs a real WebEngine, unavailable headless). The 2 skips and 1 xfail are
pre-existing conditional/environment guards.

**Mutation, re-measured.** The configured job (`setup.cfg [mutmut]`,
`backend/history_query.py` + four selected suites) produced **1,141 mutants**:
**158 killed, 1 survived, 982 "no tests"**. Reachable = 159 ⇒ **99.37%**. The
single survivor is `HistoryQuery._my_nicks` mutant 7, the one Round F §9 proved
*equivalent* (no test can distinguish it without spying on `json.loads`), so the
score is effectively at its ceiling for this module. The honest reading of the
982: they measure the configured job's narrowness, not the tests' weakness —
widening the selection was measured at 910 reachable mutants and rejected for
runtime.

**Coverage holes, ranked by absolute mass** (1,250 uncovered statements across
208 files; top of the list):

| Missing stmts | Missing branches | Coverage | File |
|---:|---:|---:|---|
| **122** | **49** | 62.25% | `bridge/history_bridge.py` |
| 80 | 21 | 63.14% | `backend/cdp_client.py` |
| 55 | 21 | 78.65% | `stores/media_fetch.py` |
| 48 | 14 | 70.48% | `services/db_registry.py` |
| 42 | 14 | **21.13%** | `backend/message_injector_send.py` |
| 38 | 22 | 82.09% | `backend/config_manager.py` |
| 35 | 8 | 70.14% | `services/db_deletion_flow_remove.py` |
| 34 | 18 | 80.95% | `services/db_lifecycle.py` |
| 34 | − | 73.47% | `services/db_deletion_scan.py` |
| 30 | 11 | 73.55% | `actions/cancellation.py` |
| 29 | − | 67.29% | `bridge/layout_bridge.py` |
| 28 | 13 | 72.11% | `bridge/collector_bridge.py` |
| 27 | 8 | 87.39% | `stores/history_schema_repair.py` |
| 23 | − | 59.74% | `app/lifecycle.py` |
| 23 | − | 76.15% | `bridge/people_bridge.py` |
| 22 | 12 | 83.25% | `actions/collect_history.py` |

`backend/message_injector_send.py` is the outlier worth naming: **21.13%** on 57
statements. It owns the send-button two-stage probe (structured button probe,
`mat-icon` fallback), and the file's own 26-line JS payload is one of the 12
payloads that no harness executes. Its share of the tree is small; its share of
"code that decides whether a message is sent" is not.

**JavaScript, second measurement** (`tools/metrics/js_coverage.py`, Node v22.22.3,
29 entrypoints under coverage): **30 attributed files, 11,895 lines, 10,656
executable, 8,822 covered — 82.8%** (2026-09-13 baseline: 24 files, 80.18%).
The newly attributed files are the AI Bot Chat surface and all start strong:
`bot-chat.js` 97.5%, `bot-connection-view.js` 99.6%, `bot-settings.js` 94.9%,
`bot-prompt.js` 95.2%, `dark-select.js` 99.0%.

* **Six files are still never loaded by any Node test** — `app.js` (510),
  `stack-drag.js` (356), `url-toolbar.js` (168), `criteria-editor.js` (85),
  `composer.js` (81), `log-console.js` (39): **1,239 lines with zero JS-side
  verification.**
* Weakest loaded: `presets-ui.js` 47.3%, `sash-grid.js` 64.2%, `user-table.js`
  66.1%, `stack-dnd.js` 67.8%, `history-store.js` 70.7%, `window-presets.js` 73.1%.
* **12 embedded JS payloads / 420 lines** inside Python string constants
  (`dom_highlight.py` ×5, `dom_probe.py`, `media_handler.py`, the three
  `message_injector_*` files, `scroll_parser_dom.py`, `click_user.py`) remain
  outside every denominator — inventory only, by construction (V8 cannot see
  text that is sent over CDP).
* There is **still no JS coverage floor**. The baseline is a measurement, not a
  gate; nothing today fails if `presets-ui.js` drops another 10 points.

## 4. Code smells

**Duplication.** Two scanners, two answers, both reported:

| Tool | Groups | Lines |
|---|---:|---:|
| `tools/metrics/clone_scan.py` (AST window ≥ 6 lines) | **13** | 96 |
| `tools/metrics/current_audit.py` (exact clone) | **3** | 54 |
| `pylint R0801` (≥ 6 similar lines) | **1** | — |

All 13 `clone_scan` groups are the frozen `CLONE_BASELINE`; `rule16_gate.py
--with-clones` reports **0 new, 0 stale**, and inspection confirms they are
shared *import headers*, not copied logic. The one pylint `R0801` group is the
`actions/click_back.py` / `actions/click_main_tab.py` block-constructor pair —
RULE 3 wire shape, §16.4-sanctioned, recorded. Duplication of behaviour remains
effectively zero.

**Dead code.** `vulture --min-confidence 90`: **7 findings**, the same inventory
as the last three audits (`actions/registry.py:18` unused `Iterator` import,
`backend/cdp_client.py:35` unused `exc_type`/`tb`, `services/run/coordinator.py:62`
unused `scroll_parser`, `services/run/hooks.py:68/71/74` unused `coordinator`
protocol args).

**Unused imports (`pylint W0611`): 34 across 20 files.** These need triage, not a
sweep: most are deliberate facade re-exports. Four `find_and_click` imports carry
an explicit `# noqa: F401 (RULE 1: the shared runner)` comment;
`stores/history_db.py` re-exports seven SQL constants; `backend/dom_highlight.py`
re-exports three `COLOR_*` names. Genuinely dead and removable without a contract
change: `actions/registry.py::Iterator`, and a handful of typing imports
(`bridge/router.py` `asyncio`/`Optional`, `services/cdp_service.py` `Optional`,
`backend/tab_matcher.py` `Optional`, `bridge/people_bridge.py` `Ok`,
`bridge/undo_bridge.py` `Ok`/`Err`). The distinction matters because the AREA D
golden records public symbols, not imported names — but tests do import some of
these names, so each removal is a two-minute check, not a sed command.

**Long methods / god classes.** The 39 functions > 30 LOC and 36 classes > 150 LOC
tabulated in §1b. The four §16.5 landmine shapes the rules name (large *and*
incoherent) are now `HistoryBridge` 467/0.86, `DbLifecycle` 276/0.88,
`RunQueueMixin` 227/0.94 and `Collector` 216/0.95 — two of which (Collector,
UndoService) have already been through a decomposition round and remain the
largest of their family.

**Feature envy** — §2 above (`db_registry` → `db_deletion._append_db_files`).

## 5. Maintainability

**Maintainability index** (radon, 0–100, higher is better) over 208 files:
**mean 68.05** (was 64.85), minimum **24.9** (was 11.1), **16 files below 40**
(was 22), **0 below 20** (was 2).

| MI | Lines | File | Note |
|---:|---:|---|---|
| **24.9** | 544 | `bridge/history_bridge.py` | worst on three axes at once (size, MI, coverage) |
| 30.6 | 326 | `services/window_preset_service.py` | small and dense, not big |
| 31.0 | 314 | `services/run/progress.py` | small and dense |
| 31.5 | 464 | `stores/media_fetch.py` | long + 78.65% covered |
| 32.2 | 151 | `services/run/hooks.py` | dense |
| 33.0 | 425 | `services/collector_tick.py` | long |
| 33.7 | 128 | `app/window.py` | dense |
| 34.9 | 294 | `services/history/mutate.py` | dense |
| 35.3 | 601 | `backend/history_query.py` | worst file by size |
| 35.5 | 229 | `stores/label_assignments.py` | dense |

> **Rank caveat.** `radon mi -s` prints a *letter* band (A ≥ 20, B 10–19, C 0–9)
> looser than the classic 0–100 scale used here (≥ 85 good, 65–85 moderate,
> < 65 high risk). Every number in this section is the raw score, not the letter:
> `bridge/history_bridge.py` scores 24.9 and radon labels it **A**.

`window_preset_service.py` (326 lines / MI 30.6) and `run/progress.py`
(314 / 31.0) remain the "invisible" cases: they are not the biggest files and
would sort below any line-count triage, but they are dense — low comment ratio,
high complexity per line.

**Technical debt ratio, churn and bug density — still not honestly measurable.**

* **Churn:** this checkout carries **one commit** (`5197ce0`), a squashed import.
  A churn ranking from one commit would be fabrication, so none is given.
* **BUG density / TDR:** no defect attribution and no remediation-cost estimator
  exist in the repo. MI is the available proxy and is reported above.
* The *delta* view is available instead, and is used throughout this report: every
  "before" column is a previously **recorded snapshot**, not a guess.

## 6. New problems, prioritised (input to Round H)

Ranked by severity class, then by what is spendable without an owner decision.
The full step plan is `docs/archive/2026-09-14-round-h/ROUND_H_DESIGN_2026-09-14.md`.

| # | Problem | Evidence (this audit) | Class |
|---|---|---|---|
| **P1** | **The gate is a whitelist: 9.6% of files, 11.9% of LOC.** Debt cannot regress-detect where it lives, and `RATCHET` allows +17% growth on `HistoryQuery` | §1c: 39/39 long functions, 33/36 oversized classes, 21/23 oversized files, 11/11 wide signatures outside `OWNED` | Structural / process |
| **P2** | **The size tail is concentrated and growing slower than the tree** — 28.4% of production LOC in 23 files, worst MI 24.9 | §1b, §5 | Structural mass |
| **P3** | **Coverage holes concentrated in 16 modules; the second most-depended-upon module is 63% covered** | §3: 1,250 missing statements; `cdp_client` Ca 21 @ 63.14%; `history_bridge` 122 missing; `message_injector_send` 21.13% | Test debt |
| **P4** | **Function-length tail: 39 > 30 LOC, 195 > 20** against a 4–20 ideal; 26 functions at CC 10 have zero headroom | §1b | Structural mass |
| **P5** | **The JS half has a denominator and no floor** — 82.8%, 6 files never loaded (1,239 lines), 12 embedded payloads unharnessed | §3 | Test debt |
| **P6** | **Cohesion: 24 classes > 15 methods; four genuinely incoherent god classes remain** | §2 | Cohesion |
| **P7** | **Hygiene drift**: 16 of 23 oversized files carry no `ideal-size:` reason; one note is stale (`config_manager` says 507, file is 511); 34 unused imports untriaged | §1b, §4 | Hygiene |

## Reproduction

```bash
# environment (in-repo venv; gitignored)
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

# headless Qt on a machine without GL/NSS/X (stubs derived from the venv itself)
QT_QPA_PLATFORM=offscreen .venv/bin/python tools/build_stubs.py   # -> /tmp/stublibs

# static audit -> /tmp/audit_h.json  (complexity, size, LCOM, coupling, MI, clones)
.venv/bin/python tools/metrics/current_audit.py > /tmp/audit_h.json

# radon cross-check
.venv/bin/python -m radon cc -s -j core actions backend bridge services stores app main.py > /tmp/cc_h.json
.venv/bin/python -m radon mi -s core actions backend bridge services stores app main.py | head

# RULE 16 gate, including the clone ratchet
.venv/bin/python tools/metrics/rule16_gate.py --with-clones

# full suite + coverage (branch), the §16.3 scope
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs COVERAGE_FILE=/tmp/.coverage_h \
  .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q -p no:cacheprovider \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/tmp/.coverage_h .venv/bin/python -m coverage json -o /tmp/coverage_h.json

# mutation score (scoped by setup.cfg; ~1 min; delete mutants/ afterwards)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut run --max-children 2
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut results --all true

# smells
.venv/bin/python tools/metrics/clone_scan.py .
.venv/bin/vulture --min-confidence 90 core actions backend bridge services stores app main.py
.venv/bin/pylint --disable=all --enable=R0801 --min-similarity-lines=6 --ignore=tests,tools \
  core actions backend bridge services stores app main.py
.venv/bin/pylint --disable=all --enable=W0611 --ignore=tests,tools \
  core actions backend bridge services stores app main.py

# JavaScript: 29 entrypoints, then the V8 coverage measurement
for f in tests/test_*.js; do node "$f" || echo "FAIL $f"; done
.venv/bin/python tools/metrics/js_coverage.py --json /tmp/js_cov_h.json
```

Measured on this machine, in this order, on 2026-09-14 (Python 3.11.2,
Node v22.22.3, PySide6 6.11.2): audit 4.6 s, gate 0.3 s (19 s with clones),
suite **471 s**, mutation ~5 min with `--max-children 2`, JS suite 8.2 s,
JS coverage 8.7 s.

**Environment notes.** `tools/build_stubs.py` is required on this sandbox
(no `libGL.so.1`); it compiles version-scripted stubs from the venv's own ELF
NEEDED entries into `/tmp/stublibs`. `coverage.json` and `mutants/` are **not**
gitignored, so both were written to `/tmp` / deleted after the run — the tree is
clean (`git status --short` empty) and no production file was modified to produce
this audit.
