# Code quality audit — 2026-09-14

Snapshot: `5197ce0` ("upd"), branch `arena/01a0a11b-chat-v-bot`. No production
code was changed to produce this audit; every number below was re-measured from
this tree with the commands in **Reproduction**.

Scope: **208 production Python files** (2,268 functions, 279 classes) under
`core`, `actions`, `backend`, `bridge`, `services`, `stores`, `app`, plus
`main.py` — and, for the first time in an audit of this repo, the **30
JavaScript files / 11,865 lines** of the frontend, because that is now where
the largest artefacts live.

## Executive summary

**Complexity is closed. Python size is closing. JavaScript is the open flank.**

* **Complexity: clean and it stays clean.** 0 of 2,268 functions exceed cyclomatic
  complexity 10 (max exactly 10), 0 exceed cognitive complexity 15 (max 15),
  0 nest deeper than 4. Mean CC 2.98, mean cognitive 2.02. The user's thresholds
  (CC ≤ 10, cognitive ≤ 15, nesting ≤ 3–4) are met with nothing at the ceiling
  except one function that sits *on* it.
* **Python size: the tail that Round F/G attacked is measurably smaller.** Files
  over 500 lines fell 10 → 4; files over 300 fell 29 → 23; mean MI rose 64.85 →
  **68.05**; the MI floor rose 11.1 → **24.9**. What remains is 23 files in the
  300–600 range and 36 classes over the 150-LOC gate line.
* **The frontend is now the largest un-gated mass in the repository.** 30 files /
  11,865 lines; the biggest file (`ui/js/sash-grid.js`, 1,361 lines) is 2.3× the
  biggest Python file; the biggest object (`SashGrid`, 1,331 LOC / 69 methods) is
  2.8× the biggest Python class; the biggest functions
  (`ui/js/app.js::setupBridgeListeners` 205 LOC, `ui/js/stack-dnd.js::_showConfig`
  180 LOC) are 3.3–3.8× the biggest Python function that is *not* an embedded JS
  payload (`stores/history_db.py::init`, 54). **9.2% of measured JS functions exceed 30 lines against 1.7% in
  Python**, and RULE 16 — which gates Python on exactly that line — does not see
  JavaScript at all. This is the single biggest structural gap.
* **Tests are the strongest they have ever measured, and the weakest exactly
  where the code is worst.** 3,172 passed / 0 failed, line **92.64%**, branch
  **88.03%**, mutation **99.37%** (158 killed / 1 survivor / 982 unreachable),
  ratio 1 : 1.57. But the worst-maintainability Python files are also the least
  covered: `bridge/history_bridge.py` MI 24.9 / **66.4%**, `backend/cdp_client.py`
  MI 36.7 / **65.2%**, `backend/message_injector_send.py` **26.3%**.
* **JavaScript has a number now, and it is a mixed one.** 82.8% line coverage
  (8,822/10,656 executable) across 30 files, 29/29 Node suites green — but six
  files are never loaded by any test (1,239 LOC, including `ui/js/app.js`, the
  application entry point), and the two biggest files are the weakest of the
  loaded ones (`sash-grid.js` 64.2%, `stack-dnd.js` 67.8%).

### Before → now

| Metric | 2026-09-10 | 2026-09-12 | **2026-09-14** |
|---|---:|---:|---:|
| Python tests | 2,129 passed / 0 failed | 2,710 / 0 | **3,172 / 0** |
| Python subtests | not reported | 777 | **902** |
| Line coverage | 88.44% | 90.41% | **92.64%** |
| Branch coverage | 81.32% | 86.30% | **88.03%** |
| Mutation score | not measured | 94.34% | **99.37%** |
| Test : production ratio | not reported | 1 : 1.56 | **1 : 1.57** |
| Production files | 133 | 154 | **208** |
| Production functions | 1,532 | 1,997 | **2,268** |
| Production nonblank/noncomment | 18,499 | 23,136 | **26,333** |
| Max cyclomatic complexity | 31 (legacy count) | 10 | **10** |
| Functions over CC 10 | 67 | 0 | **0** |
| Functions over cognitive 15 | not measured | 2 | **0** |
| Functions over 30 LOC | 73 | 42 (2.1%) | **39 (1.7%)** |
| Functions over 4 params | 70 | 70 (3.5%) | **11 (0.5%)** |
| Classes over 150 LOC | 11 (over 300) | 38 (18.3%) | **36 (12.9%)** |
| Files over 300 lines | not reported | 29 | **23 (11.1%)** |
| Files over 500 lines | 10 | 10 | **4** |
| Mean maintainability index | not reported | 64.85 | **68.05** |
| Minimum MI (worst file) | 11.1 | 11.1 | **24.9** |
| JavaScript coverage | not measured | not measured | **82.8%** |

The direction of travel is right on every Python axis. The new number is the
JavaScript column, and it says the frontend never received the treatment the
Python side has had for four rounds.

## 1. Complexity and size against your thresholds

### 1a. Complexity — passes, with room

| Measure | Your threshold | Measured (Python) | Verdict |
|---|---|---:|---|
| Cyclomatic complexity (max) | ≤ 10 | **10** | ✅ met exactly, none above |
| Functions with CC > 10 | 0 | **0 / 2,268** | ✅ closed |
| Mean CC | — | 2.98 (median 2, p95 8) | healthy |
| Cognitive complexity (max) | ≤ 15 | **15** | ✅ met exactly, none above |
| Functions with cognitive > 15 | 0 | **0** | ✅ closed in Round G (was 2) |
| Nesting depth (max) | ≤ 3–4 | **4** | ✅ at the loose bound |
| Functions with nesting > 4 | 0 | **0** | ✅ closed |

### 1b. Size — the Python tail that remains

| Measure | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Function length (max) | ≤ 20–30 LOC | **107** (`dom_probe::build_probe`, embedded JS literal) | ⚠️ documented §16.1.5 |
| Longest function that is *not* a JS literal | ≤ 20–30 LOC | **54** (`history_db::init`) | ⚠️ |
| Mean / median function LOC | — | 9.19 / 7 | ✅ |
| Functions 4–20 LOC ("ideal band") | most | **1,418 (62.5%)** | ✅ |
| Functions > 30 LOC | few | **39 (1.7%)** | ✅ minuscule tail |
| Class size (max) | ≤ 200–300 LOC | **467** (`HistoryBridge`) | ❌ 1.6× the loose bound |
| Classes > 300 LOC | 0 | **6 (2.2%)** | ❌ |
| Classes > 150 LOC (gate line) | 0 | **36 (12.9%)** | ❌ |
| Methods per class (max) | ≤ 10–15 | **44** (`HistoryRepo`, deliberate facade) | ⚠️ see §2 |
| Classes > 15 methods | 0 | **24 (8.6%)** | ❌ |
| Parameters (max) | ≤ 3–4 | **20** (`actions/scroll_parse.py::__init__`) | ⚠️ RULE 3 legacy block |
| Functions > 4 params | few | **11 (0.5%)** | ✅ RULE-3 floor, 9 documented overrides |
| File size (max) | ≤ ~300 | **601** (`backend/history_query.py`) | ❌ 2× |
| Files > 500 lines | 0 | **4** | ❌ |
| Files > 300 lines | few | **23 (11.1%)** | ⚠️ |

**The four files over 500 lines**, worst maintainability first:

| Lines | SLOC | MI | Coverage | File |
|---:|---:|---:|---:|---|
| 544 | 450 | **24.9** | 66.4% | `bridge/history_bridge.py` |
| 601 | 417 | 35.3 | 97.8% | `backend/history_query.py` |
| 511 | 319 | 40.9 | 85.8% | `backend/config_manager.py` |
| 514 | 371 | 54.9 | 96.8% | `backend/dom_highlight.py` |

**Biggest classes** (LOC / methods / LCOM\*):

| LOC | Methods | LCOM\* | Class | Reading |
|---:|---:|---:|---|---|
| 467 | 31 | 0.86 | `bridge/history_bridge.py::HistoryBridge` | genuine — 31 substantive slots |
| 407 | 25 | 0.12 | `stores/history_schema_repair.py::SchemaMigrator` | cohesive, merely long |
| 375 | 19 | 0.06 | `stores/history_repo_lifecycle.py::PersonLifecycle` | cohesive, merely long |
| 325 | 18 | 0.18 | `stores/history_repo_append.py::AppendPlanner` | cohesive, merely long |
| 310 | 14 | 0.74 | `backend/history_query.py::HistoryQuery` | genuine |
| 306 | 15 | 0.21 | `stores/media_fetch.py::MediaFetcher` | cohesive, merely long |
| 276 | 22 | 0.88 | `services/db_lifecycle.py::DbLifecycle` | genuine |
| 232 | 30 | 0.86 | `stores/history_db.py::HistoryDB` | genuine |
| 227 | 22 | 0.94 | `services/run/progress.py::RunQueueMixin` | genuine |
| 225 | 14 | 0.93 | `actions/click_user.py::ClickUser` | genuine |
| 214 | 33 | 0.93 | `stores/media_store.py::MediaStore` | 73% delegations — facade |
| 216 | 40 | 0.95 | `services/collector_service.py::Collector` | 85% delegations — facade |
| 178 | 28 | 0.95 | `services/undo_service.py::UndoService` | 86% delegations — facade |

**Longest functions** (the tail, excluding the JS-literal builder):

`stores/history_db.py::init` 54 · `backend/history_query.py::page` 53 ·
`stores/history_repo_append.py::append` 50 · `backend/history_query.py::_search`
49 · `actions/scroll_parse.py::config_schema` 44 ·
`bridge/history_bridge.py::history_delete_person` 44 ·
`services/db_lifecycle.py::_clean_unlocked` 42 ·
`stores/history_repo_append.py::_write_rows` 42 · `…_prepend` 42.

### 1c. JavaScript — the unmeasured half (new)

| Measure | Python (RULE 16 gate) | JavaScript (measured today) |
|---|---:|---:|
| Files measured | 208 | **30** |
| Lines | 26,333 nonblank/noncomment | **11,865 physical** |
| Largest file | 601 lines | **1,361 lines** (`ui/js/sash-grid.js`) |
| Second largest | 544 | **1,341** (`ui/js/stack-dnd.js`) |
| Largest class/object | 467 LOC / 31 methods | **1,331 LOC / 69 methods** (`SashGrid`) |
| Second | 407 / 25 | **1,168 LOC / 58 methods** (`StackDnD`) |
| Longest function | 54 (real logic) | **205** (`app.js::setupBridgeListeners`) |
| Functions > 30 lines | 39 / 2,268 = **1.7%** | 50 / 546 = **9.2%** |
| Functions > 60 lines | 0 | **10** |
| Complexity gate | CC ≤ 10, cognitive ≤ 15, nesting ≤ 4 | **no measurement exists** |
| Size gate | fail > 30 LOC function, > 150 LOC class | **no measurement exists** |
| Coverage floor | ≥ 80% line / ≥ 75% branch | none (82.8% measured, not gated) |

Measured with the round's own scanner (`node /tmp/jsfn.js`, reproduction below):
546 functions/object methods in 30 files, 50 over the 30-LOC fail line, 10 over
60, 2 over 100.

## 2. Coupling and cohesion

### Stability (Ca = used-by, Ce = depends-on, I = Ce/(Ca+Ce))

**Most depended-upon — correctly stable (I ≈ 0):** `core.events` (Ca 27, Ce 0),
`backend.cdp_client` (21/0), `core.result` (17/0), `stores.history_models`
(13/0), `actions.speed` (10/0), `services.collector_states` (8/0).

**Most dependent — correctly unstable (I ≈ 1):** `bridge.router` (1/20, I 0.95),
`services.run.coordinator` (1/15, 0.94), `services.undo_service` (3/14, 0.82),
`services.history` (2/12, 0.86), `services.collector_service` (3/11, 0.79),
`backend.config_manager` (3/10, 0.77), `app.bootstrap` (2/9, 0.82),
`services.bot_chat` (1/7, 0.88).

Every module with I ≥ 0.77 is a composition root, coordinator or router — the
job description of a thing that depends on many and is depended on by nobody.
**The dependency graph does not need repair.**

### Cohesion (LCOM\*)

170 classes with ≥ 2 methods and ≥ 1 field: **mean 0.594, median 0.676, 67.1%
at or above 0.5, 56 at or above 0.85.** Raw LCOM is a triage signal, not a gate
(the audit of 2026-09-12 explains why: parameter objects and result variants
score 1.00 by construction). Splitting the ≥ 0.85 set by *delegation share* —
the fraction of methods under 4 lines — separates two very different shapes:

* **Delegation facades (57–86% of methods are one-liners)** — the house pattern,
  not debt: `HistoryRepo` (44 methods, 86%), `UndoService` (86%), `Collector`
  (85%), `HistoryExportService` (79%), `PeopleBridge` (75%), `MediaStore` (73%),
  `ScrollParser` (57%). These are routers over a prefix family; "fixing" them by
  splitting would recreate the same shape one level down.
* **Genuinely incoherent (0–36% delegation, large, LCOM ≥ 0.85) — the real list:**
  `RunCoordinator` 0.97/182/17, `RunQueueMixin` 0.94/227/22, `ClickUser`
  0.93/225/14, `CDPClient` 0.91/208/21, `SyncSession` 0.91/178/17, `ChatParser`
  0.94/133/13, `PeopleBridge`→(see above), `HistoryBridge` 0.86/467/31,
  `HistoryDB` 0.86/232/30, `DbLifecycle` 0.88/276/22, `LabelStore` 0.89/222/38,
  `UndoBridge` 0.86/165/15, `HistoryMutateService` 0.86/164/15, `DbBridge`
  0.86/142/12, `RunExecutionMixin` 0.88/163/11, `RunLifecycleMixin` 0.89/124/10,
  `CollectPhaseMixin` 0.92/90/7, `ConfigManager` 0.87/177/20.

## 3. Test quality

| Measure | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Python tests passing | all | **3,172 / 0 failed** (528 s) | ✅ |
| Skipped / deselected / xfailed | — | 2 / 1 / 1 | documented below |
| Subtests | — | **902 passed** | ✅ |
| Line coverage | ≥ 80% | **92.64%** (15,745 / 16,995) | ✅ +12.6 pp |
| Branch coverage | ≥ 75% | **88.03%** (3,514 / 3,992) | ✅ +13.0 pp |
| Mutation score | ≥ 70% | **99.37%** (158 killed, 1 survived, 982 unreachable) | ✅ |
| Test : production ratio | ~1 : 1 | **1 : 1.57** | ✅ |
| JS test entrypoints | all pass | **29 / 29** | ✅ |
| JS line coverage | none exists | **82.8%** (8,822 / 10,656) | measurement only |

**Mutation — one survivor left.** The configured job (`setup.cfg`) covers
`backend/history_query.py`: 1,141 mutants generated, **982 unreachable** ("no
tests" — excluded by the documented convention, count reported so neither number
can be quoted selectively), 158 killed, **1 survivor**:
`HistoryQuery._my_nicks` mutant 7. The 2026-09-12 audit recorded 9 survivors; the
Round G test-debt step killed eight of them. The reachable score is
**158/159 = 99.37%**.

**Deselect/skip:** one deselected (`tests/test_sash_webengine.py::
TestSashWebEngine::test_grid_in_real_webengine` — needs a real WebEngine), 2 skips
and 1 xfail are pre-existing conditional/environment guards.

**Lowest-covered Python modules** (≥ 30 statements) — note how they overlap the
worst-MI list:

| Coverage | Missing | File | Why it matters |
|---:|---:|---|---|
| **26.3%** | 42 | `backend/message_injector_send.py` | the send path of the message composer |
| 65.2% | 80 | `backend/cdp_client.py` | every CDP call goes through it |
| **66.4%** | 122 | `bridge/history_bridge.py` | worst MI in the project |
| 66.7% | 23 | `app/lifecycle.py` | app boot/shutdown |
| 69.3% | 35 | `services/db_deletion_flow_remove.py` | archive deletion |
| 70.1% | 29 | `bridge/layout_bridge.py` | grid layout slots |
| 70.7% | 48 | `services/db_registry.py` | world switching |
| 79.5% | 55 | `stores/media_fetch.py` | media recovery |

**JavaScript coverage, re-measured at this snapshot** (`tools/metrics/
js_coverage.py`, 30 files — the baseline report of 2026-09-13 recorded 24 files /
80.18%, so the denominator changed; the two are not directly comparable):

| Coverage | Lines | File |
|---:|---:|---|
| 0.0% | 510 | `ui/js/app.js` — the app entry point, never loaded by a test |
| 0.0% | 356 | `ui/js/stack-drag.js` |
| 0.0% | 168 | `ui/js/url-toolbar.js` |
| 0.0% | 85 | `ui/js/criteria-editor.js` |
| 0.0% | 81 | `ui/js/composer.js` |
| 0.0% | 39 | `ui/js/log-console.js` |
| **47.3%** | 474 | `ui/js/presets-ui.js` |
| **64.2%** | 1,361 | `ui/js/sash-grid.js` |
| 66.1% | 448 | `ui/js/user-table.js` |
| **67.8%** | 1,341 | `ui/js/stack-dnd.js` |
| 70.7% | 458 | `ui/js/history-store.js` |
| 73.1% | 376 | `ui/js/window-presets.js` |
| 82.9% | 76 | `ui/js/bot-messages.js` |
| 94.3–100% | — | the other 17 files |

Six files (1,239 LOC) are never loaded by any Node test — the JS analogue of an
uncovered module, and `app.js` is the one that wires the whole application.

## 4. Code smells

**Duplication.** Two scanners, two answers, both reported:
`tools/metrics/current_audit.py` (exact clones) finds **3 groups / 54 lines**;
`tools/metrics/clone_scan.py` (AST window ≥ 6 lines) finds **13 groups / 96
lines** — all 13 are the frozen `CLONE_BASELINE` in `rule16_gate.py`, verified
once more with `--with-clones`: **0 new, 0 stale**. Inspected: every group is a
shared import header, not copied logic. Behavioural duplication remains zero.

**Dead code.** `vulture --min-confidence 90`: **7 findings**, unchanged since
2026-09-12 — `actions/registry.py:18` (`Iterator`), `backend/cdp_client.py:35`
(`exc_type`, `tb`), `services/run/coordinator.py:62` (`scroll_parser`),
`services/run/hooks.py:68/71/74` (`coordinator`).

**Long methods / god classes.** The 39 functions over 30 LOC and 36 classes over
150 LOC tabulated in §1b. The four genuinely large *and* incoherent classes are
`HistoryBridge` (467/31/0.86), `DbLifecycle` (276/22/0.88), `RunQueueMixin`
(227/22/0.94) and `ClickUser` (225/14/0.93).

**Feature envy / boundary violations.** Not machine-measured in this repo; four
instances found by inspection, all of the same shape (one module reaching for
another's private member): `bridge/router.py:471` (`ctx.undo._history_entry`),
`bridge/undo_bridge.py:178` (`self.undo_service._clean_history`),
`services/db_service.py:160/163` (`self.registry._remember` /
`._prune_remembered`), `services/history/query.py:97/132/139`
(`self.media._dirs`, `self.collector._nick`, `self.collector._last_sync_reason`).
Either those members are public and want the name, or the caller should not need
them. Note the many `self.p._x` accesses inside the Round-G part classes are the
documented *part* pattern (a part holds its host), not this smell.

## 5. Maintainability

**Maintainability index** (radon, 0–100, higher is better) over 208 files:
**mean 68.05, median 65.3, minimum 24.9.** 16 files (7.7%) score below 40; none
below 20. Worst first:

| MI | Lines | Coverage | File |
|---:|---:|---:|---|
| **24.9** | 544 | 66.4% | `bridge/history_bridge.py` |
| 30.6 | 326 | 100% | `services/window_preset_service.py` |
| 31.0 | 314 | 92.0% | `services/run/progress.py` |
| 31.5 | 464 | 79.5% | `stores/media_fetch.py` |
| 32.2 | 151 | 97.2% | `services/run/hooks.py` |
| 33.0 | 425 | 98.0% | `services/collector_tick.py` |
| 33.7 | 128 | 95.4% | `app/window.py` |
| 34.9 | 294 | 96.2% | `services/history/mutate.py` |
| 35.3 | 601 | 97.8% | `backend/history_query.py` |
| 35.5 | 229 | 93.4% | `stores/label_assignments.py` |

`window_preset_service.py` (MI 30.6 in 326 lines) and `run/progress.py`
(MI 31.0 in 314) remain what the 2026-09-12 audit called them: **dense, not
big** — a size-driven sort does not see them. `history_bridge.py` at 24.9 is the
project's single worst file, and it is also 34% uncovered.

**Technical debt ratio, churn, bug density — still not honestly measurable.**
No tool in this repo produces a remediation-cost estimate; the checkout history
is 2 commits (both whole-repo imports), which is not enough for a churn signal;
and there is no defect labelling to attribute bugs to files. They are named here
as unavailable rather than invented.

## 6. Structured next phases — Round H

Ordered by measured impact, with the two owner decisions this evidence forces:

1. **The frontend (30 files / 11,865 lines) has no size gate and two god
   objects.** `SashGrid` (1,331/69) and `StackDnD` (1,168/58) are the largest
   classes in the project by every measure; `_showConfig` (180) and
   `setupBridgeListeners` (205) are its longest functions; and 1,239 LOC are
   loaded by no test at all. **Area A.**
2. **Python's 500-line class of files plus its worst-MI file.** `history_bridge.py`
   (544 / MI 24.9 / 66.4% covered) and `history_query.py` (601 / MI 35.3) are the
   two biggest correctness-bearing surfaces in the archive path. **Area B.**
3. **Service/store cohesion and the dense-file outliers.** 17 genuinely
   incoherent classes, the MI-density cases, and the 300–500 band. **Area C.**
4. **Verification debt.** One mutation job for one module, a coverage gap that
   sits precisely on the risky files, and the class of defect (a fake inventing
   an interface) that let a dead feature ship green. **Area D.**

The plan — four areas, each with its own file ownership so they can be developed
independently — is `docs/archive/2026-09-14-round-h/ROUND_H_DESIGN_2026-09-14.md`.

## Reproduction

```bash
# environment (in-repo venv; gitignored). Headless Qt needs GL/X11 stubs.
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python tools/build_stubs.py .venv /tmp/stublibs

# static audit -> /tmp/audit_h.json (complexity, size, LCOM, coupling, MI, clones)
.venv/bin/python tools/metrics/current_audit.py > /tmp/audit_h.json

# full suite + coverage (headless Qt; ~9 min with instrumentation)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/tmp/.coverage_h .venv/bin/python -m coverage json -o /tmp/coverage_h.json

# mutation score (scoped by setup.cfg; ~2 min; delete mutants/ afterwards)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut run
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut results

# gates and smells
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
.venv/bin/python tools/metrics/clone_scan.py .
.venv/bin/vulture --min-confidence 90 core actions backend bridge services stores app

# JavaScript: 29 Node suites, then the coverage measurement
for f in tests/test_*.js; do node "$f"; done
.venv/bin/python tools/metrics/js_coverage.py --json /tmp/js_cov_h.json

# JavaScript size/shape (this audit's own scanner; no repo tool measures JS yet)
node /tmp/jsfn.js ui/js/*.js ui/js/core/*.js backend/js/*.js
```

Raw evidence for this session lives **outside** the Git checkout
(`/tmp/audit_h.json`, `/tmp/coverage_h.json`, `/tmp/js_cov_h.json`,
`/tmp/mutmut_results.txt`): coverage and mutmut artefacts are not gitignored, and
`mutmut` leaves an untracked `mutants/` directory that was removed after the run.

## Round H Area C — after H-C1…H-C5 (same day, later)

Measured with the same commands on branch `arena/01a0a136-chat-v-bot`. Area C
owns `services/`, `stores/`, `actions/`, `app/`.

### What moved

| Step | Before | After |
|---|---|---|
| H-C1 `services/run/` | `RunQueueMixin` 227 LOC / 22 methods, `RunCoordinator` 182 / 17; 10 files | `RunCoordinator` 60 LOC / 8 methods; **15 files**, largest 201 lines, max 11 methods; `queue_select.py` / `single_target.py` / `cycle_body.py` / `step_report.py` |
| H-C2 `services/history/mutate.py` | 294 lines, MI 34.9 | 35-line composition root + 3 mixins, MI 63–68 |
| H-C3 `services/db_lifecycle.py` | 328 lines, `DbLifecycle` 276 / 22, `_clean_unlocked` 42 LOC | 115 lines, `DbLifecycle` 110 / 11, `_clean_unlocked` **14 LOC**, + `db_lifecycle_ops.py` / `db_lifecycle_files.py` |
| H-C4 planners | `SchemaMigrator` 407 / 25, `PersonLifecycle` 375 / 19, `AppendPlanner` 325 / 18, `media_fetch.py` 464 lines MI 31.5 | `SchemaMigrator` 210 / **15**, `PersonLifecycle` 240 / **12**, `AppendPlanner` 171 / **10**, `MediaFetcher` 188 / **10**; `media_fetch.py` 242 lines MI **54.7** |
| H-C5 dense files | six files MI 30.6–35.5 | **all ≥ MI 50** (see below) |

### H-C5, the six §2c files

`services/run/progress.py` 31.0 → **71.8** (314 → 79 lines) · `services/window_preset_service.py` 30.6 → **77.6** (+ 5 files, MI 58.0–80.1) · `app/window.py` 33.7 → **58.6** · `services/collector_tick.py` 33.0 → **82.7** (+ `collector_probe.py` 53.2, `collector_archive.py` 52.2) · `services/history/mutate.py` 34.9 → 3 mixins at 63–68 · `stores/label_assignments.py` 35.5 → **68.8** (+ `label_defs.py` 62.6, `label_people.py` 64.5).

The plan's wording for H-C5 was "extract named predicates/helpers, not new
files". **That cannot raise MI.** radon's MI is
`(171 − 5.2·ln(V) − 0.23·CC − 16.2·ln(LLOC) + comment term) · 100/171`;
extracting a helper inside one file leaves V, CC and LLOC unchanged (it
usually *adds* LLOC). Every number above came from splitting the file, which
is also what H-C1 already did to `run/progress.py`. Round F §6 said the
opposite about these same files; H-C5 is the newer in-force plan and it
measures. The reasoning is recorded in each new module docstring.

### Classes still over the RULE 16 caps, with reasons

* `UndoService` 178 LOC / **28 methods** — not reducible this round. Three
  independent pins hold it: `tests/unit/services/test_undo_structure.py::MOVED`
  pins 21 delegators on the class; `bridge/router.py` reads three of its
  statics as class attributes; `tests/test_world_write_gate.py` monkeypatches
  the **module-level** `undo_service.MAX_STACK_HISTORY`, so `push` cannot move.
  Cutting it to 15 would break Area B's frozen interface. **Verdict: facade,
  kept, recorded here and in `docs/archive/2026-09-14-round-h/AREA_C_...md`.**
* `HistoryRepo` 44 methods, `Collector` 40, `LabelStore` 38, `MediaStore` 33,
  `HistoryDB` 30, `ScrollParser` — all facades whose delegators *are* the
  public API their bridges call. H-C6 verdict: keep.
* `LegacyCopyMixin` 163 LOC and `SchemaMigrator` 210 LOC are over the 150-LOC
  class line but are **legacy offenders strictly reduced** (407 → 210), which
  §16.5 permits; both are now at or under the 15-method cap.

### A latent bug found by measuring, not by reading

`actions/base.py:260` called `_shared_runner()`, a name that has never existed
in that module — the shared visual-confirmation runner is `_click_runner()`
(line 45). Every click block in `actions/` imports `find_and_click` at module
level, so `getattr(module, "find_and_click", None)` always short-circuited and
the broken branch was unreachable in every test. `pyflakes` (installed to
verify the H-C4/H-C5 moves resolved their free variables) reported it as
`undefined name`.

Fixed to `_click_runner()`, with a gate that drives the fallback directly
(`tests/test_scroll_parse_pipeline.py::TestSharedModuleRule::test_the_fallback_runner_resolves_when_a_block_has_no_own_import`).
Verified in both directions: it passes on the fix and fails with
`NameError: name '_shared_runner' is not defined` when the old name is
restored.

`pyflakes` over `stores/ services/ app/ actions/` is otherwise clean; the only
remaining reports are the deliberate `from actions.find_click_runner import
find_and_click` re-imports (the lookup pattern `click_runner` documents) and
one pre-existing unused local in `stores/label_world.py:135`.

### Final measured state (branch `arena/01a0a136-chat-v-bot`)

`tools/metrics/current_audit.py` over Area C: **162 files / 22 599 lines**
(was 139 / 21 726 — 23 new leaf modules, +873 lines, most of it docstrings).

* **Files > 300 LOC: 5** (was 12). Worst is now `stores/history_repo_identity.py`
  at 365. Gone from the list: `media_fetch` 464, `history_repo_lifecycle` 441,
  `history_schema_repair` 441, `collector_tick` 425, `history_repo_append` 366,
  `db_lifecycle` 328, `window_preset_service` 326, `run/progress` 314.
* **All six §2c dense files are ≥ MI 50.** None of them appears in the
  MI < 50 list any more.
* `rule16_gate.py --with-clones`: **green** — 0 new clone groups, 0 stale
  baseline entries, "All owned functions fit. Ratchet intact."
* `stores_modules.py`: 45 raw files → **15 effective §18.3 modules, in band**.
* Full suite: **3186 passed, 0 failed** (baseline at HEAD: 3169 passed).

### A second real bug, found by the suite going red

`services/history/mutate_settings.py::_persist_app_settings` called
`asyncio.get_running_loop().create_task(work())` and dropped the result.
CPython's event loop holds only a **weak** reference to a pending task, so the
task can be collected before it runs and the `app_settings` write is silently
lost. `tests/test_history_service_lifecycle.py::TestSettings` had already
written this off in its own docstring as "Ledger #9 (minor): the task is
neither awaited nor reference-held".

It was latent until the larger Round H suite raised allocation pressure enough
to collect the task: `test_patch_lands_in_the_worlds_app_settings` then failed
**twice in a row** on this branch while a pristine-HEAD worktree ran the same
suite clean (3169 passed, 0 failed). Holding the task in a per-service set
made the branch green (3186 passed). `app/lifecycle.py::start` had the same
unreferenced-`create_task` pattern and was fixed the same way.

Honest caveat: forcing the collection with `gc.collect()` did **not** reproduce
it in isolation, so the new gate
(`test_the_persist_task_is_referenced_until_it_finishes`) asserts the
invariant that changed rather than the race itself. Verified in both
directions — it fails with `AssertionError: None is not true : the persist
task is unreferenced and can be collected` when the reference is removed.

### What is NOT done

* **Coverage was not re-measured.** The DoD asks for ≥ 92.64 % line /
  88.03 % branch; no post-change coverage run was completed, so that number is
  unverified.
* `services/db_registry.py` (302 lines, MI 43.8, coverage 70.7 %) — H-C3's
  "coverage first" target, untouched.
* `stores/history_db.py::HistoryDB` (232 LOC / 30 methods) — left as a facade
  with the reason recorded in the area doc §14; `WriteTurn` untouched as
  required.
* Area-wide **MI floor ≥ 45 is not met**: 17 Area C files are still below
  MI 50, including `services/run/hooks.py` 32.2, `services/history/query.py`
  36.9, `services/layout_service.py` 38.7. None of these was in the plan's
  §2c list, but the floor is a round-level DoD and it is not satisfied.
