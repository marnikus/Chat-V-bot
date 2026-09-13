# Code quality metrics — re-measured 2026-09-12 (god-class round)

Fresh numbers on `arena/01a094dc-chat-v-bot`, after the DB-undo-restore port
and after **steps 1–3** of the god-class refactor
(`docs/archive/2026-09-12-god-classes/`). Runner and frozen definitions are the
same as the 2026-09-10 audit (`tools/metrics/current_audit.py`,
`tests/test_rule16_new_code.py`), so numbers are comparable.

## Executive summary

**The complexity gates are now fully green** — the prior rounds fixed the CC
hotspots (`_execute_cycle` 31, `_normalized` 28, `_item` 22, …). The frontier
has moved to **size & cohesion** (RULE 19 step 4), and the round is clearing
it: step 1 split the single worst file `backend/chat_sync.py` (**791 LOC, MI
10.8**) into a 10-module sub-package (worst MI 39.9); step 2 split the
deletion family (`db_deletion.py` 665 + `db_deletion_flow.py` 509 + scan 216 +
media 232 = **1 622 LOC**) into `services/db_deletion/` (11 modules, worst
`flow.py` 413); step 3 split `backend/scroll_parser.py` (**674 LOC, one
`ScrollParser` class with 34 methods**) into `backend/scroll_parser/` (11
modules, one mixin per phase, worst `probe.py` 140).

| Metric | 2026-09-10 baseline | Now (after steps 1–3) |
|---|---:|---:|
| Functions over CC 10 | 64 / 1 532 | **0 / 1 992** |
| Functions over cognitive 15 | 22 | **2** (legacy) |
| Functions over nesting 4 | 3 | **0** |
| Functions over 30 LOC | 73 | **42** |
| Files over 500 LOC | 10 | **6** |
| Worst-file Maintainability Index | 10.8 (`chat_sync.py`) | **16.1** (`window_preset_service.py`) |
| Mean Maintainability Index | 65.42 | **67.33** |
| Production files | 133 | **180** |

## 1. Complexity

Scope: 1 992 functions across 180 files (`core`, `actions`, `backend`,
`bridge`, `services`, `stores`, `app`, `main.py`).

| Metric | Fail line | Result |
|---|---|---|
| Cyclomatic complexity (Radon 6) | > 10 | **0** over; max **10** |
| Cognitive complexity (1.3.0) | > 15 | **2** over |
| Nesting depth | > 4 | **0** over; max **4** |

The two remaining cognitive outliers are pre-existing (RULE 16 §16.5: may not
*worsen*; tracked in the round plan as residual complexity, not size debt):

| Location | Cognitive | CC | Nesting |
|---|---:|---:|---:|
| `bridge/router.py` `_build_router_class` | 17 | 10 | 3 |
| `stores/settings_store.py` `get` | 17 | 7 | 4 |

## 2. Size & volume

| Metric | Fail line | Result |
|---|---|---|
| Function physical LOC | > 30 | **42** over (max 122 = `dom_probe.build_probe`, documented JS-literal exception) |
| Class physical LOC | > 150 | **36** over |
| Parameters | > 4 | **70** over (widest: `actions/scroll_parse.__init__` = 20; mostly legacy block/protocol signatures) |
| Direct methods per class | > 15 | **26** over |

Largest classes (the round's targets — see the plan):

| Class | LOC | Methods | LCOM* |
|---|---:|---:|---:|
| `Collector` | 518 | 39 | 0.93 |
| `HistoryBridge` | 474 | 31 | 0.87 |
| `UndoService` | 409 | 27 | 0.92 |
| `StackBridge` | 308 | 31 | 0.89 |
| `HistoryQuery` | 312 | 14 | 0.74 |

(`ScrollParser` — 507 LOC / 37 methods — left this table in step 3; it is now
five mixins ≤119 LOC / ≤8 methods plus a 76-LOC facade.)

## 3. Coupling & cohesion

* High afferent coupling is **reuse on shared abstractions** (expected, not a
  smell): `core.events` Ca=23, `backend.cdp_client` Ca=16,
  `actions.base_action` Ca=13, `core.result` Ca=12, `stores.history_models`
  Ca=12 — all with Ce=0 (I=0).
* High efferent coupling concentrates on the composition roots: `bridge.router`
  and `services.run.coordinator` (the run engine wiring), `app.bootstrap`.
* **LCOM*** (Henderson–Sellers, `tools/metrics/current_audit.py`): the god
  classes above score ≥ 0.87 — methods share almost no state — which is the
  machine-readable reason they are the next extraction targets.

## 4. Test quality

* **Python:** full suite (after step 1) — **2 704 passed**, 0 failed, 3 skipped,
  1 xfailed, 1 deselected, 1 warning. (The 4 snapshot failures that the split
  briefly exposed were refreshed intentionally — see the step-1 design doc; the
  `dump_public_api` recursion fix keeps `backend/chat_sync/*` covered.)
* **Step 3 verification** (the scroll split): the five scroll suites
  (`test_scroll_parser_options`, `test_scroll_parse_pipeline`,
  `test_scroll_only_seek`, `test_filter_purge`, `test_collect_visual_and_live_refresh`)
  — **121 passed + 17 subtests**; the full `tests/unit` — **728 passed**;
  `tests/integration` — **547 passed**; the API-snapshot + stores-surface gates
  — **16 passed + 79 subtests**; `test_rule16_new_code` — **23 passed**.
* **Coverage (2026-09-12):** line **90.44%** (13 921 / 15 224), branch
  **86.36%** (3 211 / 3 718) — both *up* from the 09-10 baseline (88.44% /
  81.32%) and above the floors (≥ 80% / ≥ 75%). The step-1 relocation added no
  execution path, so the gain comes from the tests that arrived with the
  DB-undo-restore port. The "main testing gap" the 09-10 report flagged —
  `bridge` — is now **88.05% line / 80.00% branch** (was 67.44% / 48.43%).
  Remaining: `app` branch 61.76% (line 85.86%) and `main.py` 50% (1/2 branches).
* **JavaScript:** 23 frontend files / 9 237 LOC — outside the Python metric
  denominator (unchanged; the stale `test_bridge_router.js` source-location
  assertion noted in the 09-10 report is still the only known JS signal to
  repair).

## 5. Code smells

* **Duplication:** 4 exact-clone groups, 66 duplicated physical lines (the
  conservative exact-AST statement scan; unchanged across steps 1–3). The
  step-2 import-header clone (`services/db_deletion/flow.py` + `scan.py`) that
  the window-scanner in `rule16_gate.py` flags is recorded in its
  `CLONE_BASELINE` as standard-header noise, not logic.
* **Dead code:** vulture ≥ 90% — unchanged (the 7 findings from 09-10:
  `Iterator` import, unused protocol/callback args).
* **God classes / long methods:** the size table above (§2) is the inventory;
  the round plan sequences their extraction.

## 6. Maintainability

* Mean unweighted per-file Radon MI **67.33** / 100 (180 files).
* Worst files (the round's step order):
  1. ~~`backend/chat_sync.py` — 10.8~~ → **split (step 1, done)**
  2. ~~`services/db_deletion.py` — 20.5 (+ `db_deletion_flow.py` 31.5)~~ → **split (step 2, done)**
  3. ~~`backend/scroll_parser.py` — 28.4~~ → **split (step 3, done)**
  4. `services/window_preset_service.py` — 16.1
  5. `services/undo_service.py` — 23.3 · `bridge/history_bridge.py` — 23.5
  6. `services/collector_service.py` — 27.0 · `backend/history_query.py` — 33.5
  7. `backend/config_manager.py` — 40.5

* Technical-debt ratio, code churn and bug density remain unavailable on a
  shallow single-commit history (same caveat as the 09-10 report).

## Round results so far

**Step 1** — `backend/chat_sync.py` → `backend/chat_sync/` (10 modules, 21–278
LOC, worst MI 39.9). Public seam unchanged (`run_sync`, `SyncOptions`,
`merge_live`, `SLICE_RETRIES`, `SyncPersister`, `SyncSession`, `SyncPlanner`,
`MODE_*`).

**Step 2** — the deletion family → `services/db_deletion/` (11 modules;
`db_deletion.py` 665 → `plan.py` 278 / `inventory.py` 206 / leaves 15–114;
`db_deletion_flow.py` 509 → `flow.py` 413 + `state.py` 91; scan 216, media
234 unchanged as single modules). The safety tests' patch seam
(`services.db_deletion.canonical` / `.build_deletion_inventory`) is preserved,
so `tests/integration/safety_deletion/` (129) passes unmodified except two
path-target strings.

**Step 3** — `backend/scroll_parser.py` (674 LOC, one 34-method `ScrollParser`)
→ `backend/scroll_parser/` (11 modules: `constants`/`result`/`options`/
`runstate` data leaves + `probe`/`judge`/`loop`/`pipeline`/`notify` mixins +
the `parser` facade). The class is now composed of five single-responsibility
mixins (≤8 methods, ≤140 LOC); the facade owns construction and the callback/
stop seams. The `asyncio` module is re-exported so the
`sp.asyncio.sleep = spy` patch in `test_collect_visual_and_live_refresh.py`
still lands. Details and rejected dishonest reductions: the step-1/2/3 design
docs.

## Reproduction

```bash
.venv/bin/python tools/metrics/current_audit.py > audit.json
.venv/bin/radon cc -s backend/chat_sync/
.venv/bin/python tools/metrics/rule16_gate.py
.venv/bin/python tools/metrics/dump_public_api.py --diff
.venv/bin/python tools/build_stubs.py .venv /tmp/stublibs
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
.venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
.venv/bin/python -m coverage json -o coverage.json
```
