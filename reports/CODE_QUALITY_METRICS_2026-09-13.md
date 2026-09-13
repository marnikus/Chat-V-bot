# Code quality audit — 2026-09-13 (post Round G steps G1–G3)

Snapshot: `de85230`, branch `arena/01a09c20-chat-v-bot`. No production code was
changed to produce this audit. Every static number below was re-measured from
this tree with the commands in **Reproduction**. Round G's G1–G3 have landed;
G4 exists only as a design doc (no signature or file-size change).

Organised against the six requested categories: complexity, size,
coupling/cohesion, tests, smells, maintainability.

## Executive summary

**Complexity stays closed. The 500-line tail is now four files, and that is
the whole remaining size problem that still fails a glance test.**

Across **2,083** production functions there is still **not one** above
cyclomatic complexity 10 and **not one** nested deeper than 4. Cognitive
complexity > 15 is still exactly **2** functions, both undocumented legacy
offenders (the 2026-09-12 audit attributed them to the wrong symbols). Mean
CC fell again, **3.09 → 3.02**, on 86 more functions.

What Round G actually moved:

| What | 2026-09-12 audit | Now | |
|---|---:|---:|---|
| Files over 500 lines | **10** | **4** | G2/G3 split the three worst + `db_deletion_flow` |
| Worst file / worst MI | `chat_sync.py` 800 / **11.1** | `history_query.py` 601 / `history_bridge.py` **24.95** | the MI floor more than doubled |
| Mean MI | 64.85 | **66.92** | +2.07 |
| Files below MI 20 | 2 | **0** | category closed |
| Wide functions (> 4 params) | 70 | **51** | F5's floor; G4 designed, not executed |
| Functions > 30 LOC | 42 | **39** | G3's ladder/ctors |
| Production files | 154 | **186** | extraction continues |

The four remaining >500 files are `history_query.py` (601), `history_bridge.py`
(544), `dom_highlight.py` (532), `config_manager.py` (507). They are the
biggest problem in the tree. Round H starts there.

Test health is quoted from G3's last recorded run (production Python is
byte-identical to that tree aside from this audit's docs): **2,808 passed /
0 failed**, line **90.99%**, branch **87.05%**. This session re-ran the
**26 / 26** JS entrypoints (all pass) and every static scanner.

### Before → now

Previous column is `reports/CODE_QUALITY_METRICS_2026-09-12.md` (snapshot
`e4ef002`, pre-Round-F). Direction is what matters; G1–G3 sit between the
two measurements.

| Metric | 2026-09-12 | 2026-09-13 | Interpretation |
|---|---:|---:|---|
| Max Radon CC | 10 | **10** | ceiling held, none above |
| Functions above CC 10 | 0 / 1,997 | **0 / 2,083** | still closed |
| Mean Radon CC | 3.09 | **3.02** | simpler, and more of them |
| Cognitive > 15 | 2 | **2** | same count; **wrong names in the 09-12 report** (see §1a) |
| Nesting > 4 | 0 | **0** | still closed |
| Production Python files | 154 | **186** | +32 (F1–F3, G2, G3 families) |
| Production nonblank/noncomment | 23,136 | **24,291** | +5.0% |
| Test nonblank/noncomment | 36,178 | **38,112** | ratio **1 : 1.57** |
| Mean maintainability index | 64.85 | **66.92** | +2.07 |
| Min MI | 11.1 | **24.95** | `chat_sync.py` gone |
| Files > 500 lines | 10 | **4** | the Round H target |
| Files > 300 lines | 29 | **24** | 20 of them have no `ideal-size:` note |
| Classes > 150 LOC | 38 | **37** | |
| Classes > 300 LOC | 11 | **8** | `ScrollParser` 532 and `Collector` 526 left the list |
| Classes > 15 methods | 25 | **25** | facades + `Collector` 40 + two Qt bridges |
| Functions > 4 params | 70 | **51** | F5 floor; G4 not yet run |
| Functions > 30 LOC | 42 | **39** | |
| Mean / median function LOC | 9.68 / 7 | **9.46 / 7** | |
| Functions in RULE 18 band (4–20) | 63.6% of 1,997 | **62.2% of 2,083** | more 1–3-line facade delegates (expected) |
| JS test entrypoints | 26 / 26 | **26 / 26** | re-run this session |

## 1. Complexity and size against your thresholds

Scope: all **186** production Python files under `core`, `actions`, `backend`,
`bridge`, `services`, `stores`, `app`, plus `main.py`. Excludes tests, tools,
vendored assets, frontend JavaScript and generated caches.

### 1a. Complexity

| Measure | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Cyclomatic complexity (max) | ≤ 10 | **10** | ✅ met exactly, none above |
| Functions with CC > 10 | 0 | **0 / 2,083** | ✅ closed |
| Mean CC | — | 3.02 (median 2, p95 8) | healthy |
| Cognitive complexity (max) | ≤ 15 | **17** | ⚠️ 2 functions, both legacy |
| Functions with cognitive > 15 | 0 | **2 (0.10%)** | ⚠️ undocumented — see below |
| Nesting depth (max) | ≤ 3–4 | **4** | ✅ met at the loose bound |
| Functions with nesting > 4 | 0 | **0** | ✅ closed |

**The two cognitive-17 offenders are not the ones the 2026-09-12 audit
named.** That report attributed them to `backend/dom_probe.py::build_probe`.
On this tree `build_probe` scores cognitive **8**. The real two, unchanged
since at least Round G's re-measurement:

| cog | CC | nest | LOC | Function |
|---:|---:|---:|---:|---|
| 17 | 10 | 3 | 51 | `bridge/router.py::_build_router_class` |
| 17 | 7 | 4 | 17 | `stores/settings_store.py::get` |

Neither has a `quality-override:` comment. They are §16.5 legacy offenders:
must not worsen; reducing them is Round H step H7, not a drive-by.

27 functions sit exactly at CC 10 (the ceiling). None of them is new. The
longest of those is `HistoryQuery.page` (53 LOC, CC 10) — the first function
H1 extracts.

### 1b. Size — this is where the debt still lives

| Measure | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Function length (max) | ≤ 20–30 LOC | **122** | ❌ `build_probe`, §16.1.5 JS-literal exemption |
| Mean / median function LOC | — | 9.46 / 7 | ✅ far inside |
| Functions in 4–20 (RULE 18) | most | **1,295 (62.2%)** | preference, not a gate |
| Functions > 30 LOC | few | **39 (1.9%)** | ⚠️ tail |
| Class size (max) | ≤ 200–300 LOC | **467** | ❌ `HistoryBridge` |
| Classes > 300 LOC | 0 | **8** | ❌ |
| Classes > 150 LOC (the gate line) | 0 | **37 (16.0%)** | ❌ |
| Parameters (max) | ≤ 3–4 | **20** | ❌ `ScrollParse.__init__`, RULE 3 wire |
| Functions > 4 params | few | **51 (2.4%)** | ❌ G4 designed, not run |
| Methods per class (max) | ≤ 10–15 | **44** | ❌ `HistoryRepo` facade (intentional) |
| Classes > 15 methods | 0 | **25** | ❌ mix of facades and real god classes |
| File size (max) | ≤ ~300 | **601** | ❌ 2.0× the ideal |
| Files > 500 lines | 0 | **4** | ❌ **the biggest problem** |
| Files > 300 lines | few | **24** | ⚠️ 20 have no `ideal-size:` note |

### Current hotspots

**Four files over 500 physical lines** (SLOC in brackets), worst
maintainability first:

| Lines | SLOC | MI | File | Shape |
|---:|---:|---:|---|---|
| 544 | 450 | **24.95** | `bridge/history_bridge.py` | Qt `@Slot` facade; class 467 LOC / 31 direct methods / **44** via `ast.walk` (13 nested `work` closures). Ratcheted 467/44. |
| 601 | 417 | 35.27 | `backend/history_query.py` | **largest file.** `HistoryQuery` 310/14 (at the method cap), `page` 53/CC 10, `_search` 49. `PersonPageRequest` already extracted. |
| 507 | 315 | 40.82 | `backend/config_manager.py` | long-and-flat: five `_Owner` classes + `ConfigManager` 177/20 + a `DEFAULTS` blob. |
| 532 | 388 | 55.73 | `backend/dom_highlight.py` | long-and-flat: ~400 lines of JS string literals (§16.1.5) + ~130 lines of Python builders. MI is fine; the file is data. |

Three of the four carry a stale `ideal-size:` note (claimed 603/534/509,
actual 601/532/507 — two lines of drift each). `history_bridge.py`'s note
names the live QWebChannel contract and matches the file.

**Biggest classes** (LOC / methods / LCOM\\*):

| LOC | Methods | LCOM\\* | Class | Reading |
|---:|---:|---:|---|---|
| 467 | 31 | 0.86 | `bridge/history_bridge.py::HistoryBridge` | **largest class left.** Qt slots + nested `work`. |
| 406 | 25 | 0.12 | `stores/history_schema_repair.py::SchemaMigrator` | large but cohesive — helper-module extraction, not decomposition |
| 375 | 19 | 0.06 | `stores/history_repo_lifecycle.py::PersonLifecycle` | same: cohesive |
| 329 | 18 | 0.18 | `stores/history_repo_append.py::AppendPlanner` | same |
| 310 | 14 | 0.74 | `backend/history_query.py::HistoryQuery` | at the 15-method cap; H1's target |
| 308 | 31 | 0.89 | `bridge/stack_bridge.py::StackBridge` | Qt slots, low cohesion, 330-line file |
| 306 | 14 | 0.98 | `actions/scroll_parse.py::ScrollParse` | RULE 3 block; LCOM almost 1 |
| 306 | 15 | 0.21 | `stores/media_fetch.py::MediaFetcher` | cohesive |

**Most methods on one class** (the facade problem, distinct from size):

| Methods | LOC | Class | Treat as |
|---:|---:|---:|---|---|
| 44 | 228 | `stores/history_repo.py::HistoryRepo` | **facade — do not split** |
| 40 | 216 | `services/collector_service.py::Collector` | §16.5 landmine; F2 already extracted collaborators; remaining names are the host-protocol facade |
| 38 | 222 | `stores/label_store.py::LabelStore` | facade over `label_*` |
| 33 | 215 | `stores/media_store.py::MediaStore` | facade over `media_*` |
| 31 | 467 | `HistoryBridge` | Qt wire — H2 |
| 31 | 308 | `StackBridge` | Qt wire — H5 |
| 28 | 179 | `services/undo_service.py::UndoService` | F3 facade; 28 one-line delegates, leave it |

**Widest parameter lists** (unchanged since F5 — G4 not executed):

| Params | LOC | Function | Disposition |
|---:|---:|---|---|
| 20 | 29 | `actions/scroll_parse.py::__init__` | RULE 3 block wire — G4/H4 override |
| 19 | 27 | `backend/scroll_parser.py::__init__` | G4 wave 3: collapse onto `ScrollOptions` |
| 14 | 33 | `backend/chat_parser.py::sync_conversation` | G4 wave 1: `SyncRunSpec` |
| 13 | 29 | `actions/click_user.py::__init__` | RULE 3 wire |
| 13 | 54 | `stores/history_repo_append.py::append` | stores/ deferred (7 left) |
| 12 | 30 | `backend/visual_click.py::find_and_click` | G4 wave 2: `ClickRun` |

By package: `actions` 15, `backend` 13, `services` 13, `stores` 7, `bridge` 2,
`app` 1.

**Longest functions:** `dom_probe.py::build_probe` 122 (embedded JS, exempt),
`history_db.py::init` 54, `history_repo_append.py::append` 54,
`history_query.py::page` 53, `router.py::_build_router_class` 51,
`history_query.py::_search` 49. G3 removed `_run_type_strategies` 70 from this
list (now 25).

## 2. Coupling and cohesion

### Stability (Ca = used-by, Ce = depends-on, I = Ce/(Ca+Ce))

**Most depended-upon — correctly stable (I ≈ 0):**

| Module | Ca | Ce | I |
|---|---:|---:|---:|
| `core.events` | 25 | 0 | 0.00 |
| `backend.cdp_client` | 19 | 0 | 0.00 |
| `core.result` | 14 | 0 | 0.00 |
| `stores.history_models` | 13 | 0 | 0.00 |
| `actions.base_action` | 13 | 2 | 0.13 |

Ca on `core.events` rose 23 → 25 and on `cdp_client` 16 → 19 — more
consumers, still Ce = 0. The arrows still point the right way.

**Most dependent — correctly unstable leaves (I ≈ 1):**

| Module | Ca | Ce | I |
|---|---:|---:|---:|
| `bridge.router` | 1 | 17 | 0.94 |
| `services.run.coordinator` | 1 | 15 | 0.94 |
| `services.undo_service` | 3 | 13 | 0.81 |
| `services.collector_service` | 3 | 12 | 0.80 |
| `backend.config_manager` | 3 | 10 | 0.77 |
| `services.history` | 2 | 10 | 0.83 |
| `app.bootstrap` | 2 | 9 | 0.82 |

Composition roots and facades. **The dependency graph does not need repair.**

### Cohesion (LCOM\\*)

Measured over the 146 classes with a defined LCOM\\*: **mean 0.595** (was
0.650), with **96 (65.8%) at or above 0.5**.

The drop in the mean is the F2/F3/G2 splits working: `ScrollParser` 0.88 is
gone from the god-class list. LCOM\\* 1.00 is still mostly *correct*
(parameter objects, result variants, value blocks). Genuine low-cohesion
behaviour classes remaining:

| LCOM\\* | Methods | LOC | Class |
|---:|---:|---:|---|
| 0.98 | 14 | 306 | `ScrollParse` |
| 0.95 | 40 | 216 | `Collector` (facade over already-split collaborators) |
| 0.94 | 22 | 227 | `RunQueueMixin` |
| 0.89 | 31 | 308 | `StackBridge` |
| 0.86 | 31 | 467 | `HistoryBridge` |
| 1.00 | 21 | 113 | `HistoryExportService` (21 independent methods) |

`SchemaMigrator` / `PersonLifecycle` / `AppendPlanner` stay large *and*
cohesive (0.06–0.18) — size without a cohesion problem; extract helpers, do
not decompose.

## 3. Test quality

| Measure | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Python tests passing | all | **2,808 passed / 0 failed** (G3, 2026-09-13) | ✅ production unchanged since |
| Skipped / deselected / xfailed | — | 2 / 1 / 1 | same standing set |
| Line coverage | ≥ 80%; never decrease vs 90.44% | **90.99%** (G3) | ✅ |
| Branch coverage | ≥ 75%; never decrease vs 84.38% | **87.05%** (G3) | ✅ |
| Mutation score (narrow job) | ≥ 70% | **99.37%** (F6, 158/159) | ✅; F6b (module-wide) still open |
| Test : production ratio | ~1 : 1 | **1 : 1.57** | ✅ |
| JS test entrypoints | all pass | **26 / 26** (re-run this session) | ✅ |

**This session did not re-run the Python suite or mutmut.** Production Python
is the G3 tree; the only commit after G3 is the G4 design doc. Re-quoting
G3's numbers rather than inventing a new run is the honest move. The JS
harness *was* re-run here (26/26). A Round H implementation step re-runs
pytest + coverage as its equivalence gate, the way G1–G3 did.

**Coverage caveats, unchanged.** 90.99% line / 87.05% branch are Python only.
**No JavaScript coverage instrumentation** — 23 frontend JS files / 9,283 LOC
plus the JS payloads inside Python strings sit outside both denominators.
G3 recorded that `message_injector_send.py` shows ~20% because the
never-tested `click_send` family is now its own file — pre-existing debt,
visible after the split, not a regression.

**Open test-debt (from Round G §1e, still true):**

* `undo_history._migrated_entry` — no test at all (the function whose bug
  pushed app entries ahead of world entries).
* `undo_world._schedule_world_undo_save` / `restart_world` failure paths.
* `undo_apply.py` eight attributed uncovered lines.
* F6b: module-wide mutation of `history_query.py` (910 reachable vs the
  configured job's 159).
* `dbconn` rewind asymmetry vs `archive`.
* `click_send` family now measurable as its own file and still barely covered.

## 4. Code smells

**Duplication.**

| Tool | Groups | Duplicated lines |
|---|---:|---:|
| `current_audit.py` (exact clone) | 4 | 66 |
| `clone_scan.py` (AST window ≥ 6 lines) | 13 | 96 |

All 13 `clone_scan` groups match `CLONE_BASELINE` in `rule16_gate.py` —
**0 new, 0 stale**. They remain shared import headers, not copied logic,
except one real clone: `_rep` lives in both `media_handler.py` and
`message_injector_field.py` (G3 moved the injector copy; deduping it is H8
backlog, not a drive-by).

**Dead code.** `vulture` at ≥90% confidence: **7 findings**, the same set as
every audit since 2026-09-10 (`Iterator` import, `cdp_client` except-args,
`coordinator.scroll_parser` unused, three `hooks.py` protocol args). Stable.

**Unused imports (pylint W0611), expanded inventory.** Round G §1f named
four. A fresh W0611 scan of production finds **~30**, including those four
plus `datetime` in `stack_bridge.py` / `coordinator.py`, `json` in
`dom_highlight.py`, `SLICE_RETRIES`/`AppendResult` in `chat_parser.py`, a
block of `history_schema` re-exports in `history_db.py`, and several
`find_and_click` imports on click-blocks that go through the runner
indirectly. Not all are safe to delete (some are re-export seams). H8
triages them; this audit does not delete any.

**Long methods / god classes.** The 39 functions over 30 LOC and 8 classes
over 300 LOC in §1b. The genuine remaining god *classes* (large **and**
low-cohesion, not facades, not cohesive-but-long) are `HistoryBridge`,
`StackBridge`, `ScrollParse`, and the `Collector` facade (40 methods of
mostly one-line delegates — a method-count problem, not a body problem).

**Feature envy.** No automated detector. The 09-12 finding
(`db_registry` → `db_deletion._append_db_files`) was accepted as a
pylint-disable re-export in F1; not re-litigated.

## 5. Maintainability

**Maintainability index** (radon, 0–100, raw score not the letter band)
over 186 files: **mean 66.92**, minimum **24.95**. 16 files (8.6%) score
below 40; **0 below 20**.

| MI | Lines | File |
|---:|---:|---|
| **24.95** | 544 | `bridge/history_bridge.py` |
| 30.57 | 326 | `services/window_preset_service.py` |
| 31.05 | 314 | `services/run/progress.py` |
| 31.51 | 464 | `stores/media_fetch.py` |
| 32.22 | — | `services/run/hooks.py` |
| 32.86 | 425 | `services/collector_tick.py` |
| 35.27 | 601 | `backend/history_query.py` |

The 09-12 floor of 11.1 (`chat_sync.py`) is gone. The new floor is
`history_bridge.py` at 24.95 — still "high risk" on the classic scale
(< 65), but it is no longer in a class of its own. `window_preset_service.py`
and `run/progress.py` remain the density outliers: not big, *dense*. They
carry `ideal-size:` notes pointing at Round F §6; they are H6, not H1.

**Technical debt ratio, churn, bug density — still not honestly measurable.**
This checkout is a shallow Arena branch. No TDR tool, no bug-fix convention,
not enough history for churn. MI is the proxy, reported above.

## 6. Where the biggest problem is (and what is *not* it)

Ranked by severity class, then by how much of the remaining RULE 16/18
debt a step actually retires.

1. **No live product-bug class is open.** G1 closed F3c (`WriteTurn` union)
   with a negative-checked test. The suite was green at G3. Round H is a
   size round, not a correctness round.
2. **The last four files over 500 lines — this is the biggest problem.**
   Round F started with ten; G2/G3 removed six of the original ten plus
   `db_deletion_flow`. What is left is one read-path module (`history_query`,
   largest file, `page` at the CC ceiling), one Qt slot god class
   (`HistoryBridge`, worst MI, ratchet 467/44 of which 13 are nested
   `work` closures), and two long-and-flat files (`dom_highlight` = JS
   data, `config_manager` = already-separated owner classes sitting in one
   file). Freezes that used to block splitting them were lifted (Round G
   §1c F0 ruling).
3. **The 51-wide-parameter tail** is the next-largest *count*, but it is
   already designed (`G4_PARAM_OBJECTS_DESIGN_2026-09-13.md`) and does not
   retire any of the four >500 files except by shrinking a few builder
   signatures inside `dom_highlight.py`. It is a later step, not the first.
4. **Method-count god classes that are not facades** (`Collector` 40,
   `StackBridge` 31, `ScrollParse` 14 with LCOM 0.98). Facades
   (`HistoryRepo` 44, `LabelStore` 38, `MediaStore` 33, `UndoService` 28)
   stay.
5. **The 20 files in the 301–500 band with no note**, then test-debt, then
   hygiene (unused imports, stale notes, `AGENT_RULES.md` 763 vs ~730,
   docs-map drift, JS coverage).

The structured phases that follow from this ranking are Round H, designed
in
`docs/archive/2026-09-13-round-h-size-tail/ROUND_H_DESIGN_2026-09-13.md`.
**No production code is changed in this session.**

## Reproduction

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

# static audit -> stdout JSON (this session: /tmp/audit_h.json)
.venv/bin/python tools/metrics/current_audit.py

# complexity / MI
.venv/bin/radon cc -s -a core actions backend bridge services stores app main.py
.venv/bin/radon mi -s core actions backend bridge services stores app main.py

# gates and smells
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
.venv/bin/python tools/metrics/clone_scan.py .
.venv/bin/vulture --min-confidence 90 core actions backend bridge services stores app main.py
.venv/bin/pylint --disable=all --enable=W0611 core actions backend bridge services stores app main.py

# JavaScript suite
for f in tests/test_*.js; do node "$f"; done

# Python suite + coverage — last recorded at G3, not re-run this session
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
```
