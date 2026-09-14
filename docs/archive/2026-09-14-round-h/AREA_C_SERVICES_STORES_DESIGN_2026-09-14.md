# Area C design — services, stores, actions, app: cohesion, density and the 300–500 band

Round H · 2026-09-14 · owns `services/**`, `stores/**`, `actions/**`, `app/**`
Part of [`ROUND_H_DESIGN_2026-09-14.md`](ROUND_H_DESIGN_2026-09-14.md).
Source of numbers: [`reports/CODE_QUALITY_METRICS_2026-09-14.md`](../../../reports/CODE_QUALITY_METRICS_2026-09-14.md),
`/tmp/audit_h.json`, `/tmp/coverage_h.json`. **Plan only — nothing implemented.**

## 1. Why this area is third

It is the largest Python mass — **139 files / 21,726 lines**, 13 files over 300 —
but unlike Area B it is not where the worst *single* artefacts are. What it has
is two distinct, measurable problems:

1. **Cohesion:** 17 genuinely incoherent classes (large, LCOM\* ≥ 0.85, and made
   of real methods — not delegations).
2. **Density:** files whose maintainability index is low because they are
   *dense*, not long. A lines-only sort cannot see them.

Plus one thing that must **not** be done: the six delegation facades everyone's
instinct says to split.

## 2. Measured state

### 2a. The facades — do not split these (measured evidence)

| LCOM\* | LOC | Methods | Methods ≤ 3 LOC | Class |
|---:|---:|---:|---:|---|
| 0.89 | 225 | 44 | **86%** | `stores/history_repo.py::HistoryRepo` |
| 0.95 | 178 | 28 | **86%** | `services/undo_service.py::UndoService` |
| 0.95 | 216 | 40 | **85%** | `services/collector_service.py::Collector` |
| 0.99 | 80 | 14 | 79% | `services/history/export.py::HistoryExportService` |
| 0.94 | 133 | 20 | 75% | `bridge/people_bridge.py::PeopleBridge` *(Area B file)* |
| 0.93 | 214 | 33 | 73% | `stores/media_store.py::MediaStore` |
| 0.91 | 108 | 14 | 57% | `backend/scroll_parser.py::ScrollParser` *(Area B file)* |

These are routers over prefix families — the house pattern established by
`stores/history_repo*` (shim + 11 files) and `services/collector_*`. Splitting
one would reproduce the same shape one level down while breaking every caller.
**H-C6 records this verdict in writing** so a future round does not "fix" them.

### 2b. Genuinely incoherent classes (the real cohesion debt)

| LCOM\* | LOC | Methods | Class | File |
|---:|---:|---:|---|---|
| **0.97** | 182 | 17 | `RunCoordinator` | `services/run/coordinator.py` |
| **0.94** | 227 | 22 | `RunQueueMixin` | `services/run/progress.py` |
| **0.93** | 225 | 14 | `ClickUser` | `actions/click_user.py` |
| 0.92 | 90 | 7 | `CollectPhaseMixin` | `services/run/collect_phase.py` |
| **0.91** | 208 | 21 | `CDPClient` | `backend/cdp_client.py` *(Area B)* |
| 0.91 | 178 | 17 | `SyncSession` | `backend/chat_sync_session.py` *(Area B)* |
| **0.94** | 133 | 13 | `ChatParser` | `backend/chat_parser.py` *(Area B)* |
| 0.89 | 124 | 10 | `RunLifecycleMixin` | `services/run/run_lifecycle.py` |
| 0.89 | 222 | 38 | `LabelStore` | `stores/label_store.py` |
| 0.88 | 276 | 22 | `DbLifecycle` | `services/db_lifecycle.py` |
| 0.88 | 163 | 11 | `RunExecutionMixin` | `services/run/error_recovery.py` |
| 0.87 | 177 | 20 | `ConfigManager` | `backend/config_manager.py` *(Area B)* |
| 0.86 | 467 | 31 | `HistoryBridge` | `bridge/history_bridge.py` *(Area B)* |
| 0.86 | 232 | 30 | `HistoryDB` | `stores/history_db.py` |
| 0.86 | 165 | 15 | `UndoBridge` | `bridge/undo_bridge.py` *(Area B)* |
| 0.86 | 164 | 15 | `HistoryMutateService` | `services/history/mutate.py` |
| 0.86 | 142 | 12 | `DbBridge` | `bridge/db_bridge.py` *(Area B)* |

Seventeen (17) of the 170 scored classes; the rest of the ≥ 0.85 set is either a
facade (§2a) or a value/parameter object (`PersonPageRequest` 1.00 by
construction).

### 2c. The dense files — low MI in a small footprint

| MI | Lines | Coverage | File | What "dense" means here |
|---:|---:|---:|---|---|
| 30.6 | 326 | 100% | `services/window_preset_service.py` | many small decisions, few named predicates; `WindowPresetService` is only 27 LOC — the mass is module-level logic |
| 31.0 | 314 | 92.0% | `services/run/progress.py` | `RunQueueMixin` 227/22 (label filtering, queue ordering, single-target guard, take phase) |
| 33.0 | 425 | 98.0% | `services/collector_tick.py` | `CollectorArchive` 183/12 beside module logic |
| 33.7 | 128 | 95.4% | `app/window.py` | window construction + menu/shortcut wiring in 128 lines |
| 34.9 | 294 | 96.2% | `services/history/mutate.py` | `HistoryMutateService` 164/15: settings, gaze, legacy rows, world entries, undo entries |
| 35.5 | 229 | 93.4% | `stores/label_assignments.py` | `LabelAssignments` 184/18 (LCOM 0.12 — cohesive, just dense) |

These are invisible to a `wc -l` sort and are why RULE 19 puts *naming* before
*splitting*: the remedy is usually extracting named predicates/helpers, not new
files.

### 2d. The store planners — cohesive but three times over the ideal

| LOC | Methods | LCOM\* | Class | File | Coverage |
|---:|---:|---:|---|---|---:|
| 407 | 25 | 0.12 | `SchemaMigrator` | `stores/history_schema_repair.py` (441 lines) | 87.9% |
| 375 | 19 | 0.06 | `PersonLifecycle` | `stores/history_repo_lifecycle.py` (441) | 96.2% |
| 325 | 18 | 0.18 | `AppendPlanner` | `stores/history_repo_append.py` (366) | — |
| 306 | 15 | 0.21 | `MediaFetcher` | `stores/media_fetch.py` (464, **MI 31.5**) | 79.5% |

High cohesion, low LCOM — these need **helper-module extraction by named
responsibility** (§16.1.1), not decomposition by responsibility: e.g.
`SchemaMigrator`'s legacy-rebuild ladder (`_rebuild_legacy_messages` 32,
`_rebuild_messages_constraint` 39, `_copy_legacy_rows`, `_copy_one_legacy`,
`_finish_legacy_rebuild`) is one named concept — "the legacy rebuild" — that can
live in its own module while the class keeps the phase orchestration.

### 2e. The 300–500 band in this area

`services/db_lifecycle.py` 328 (MI 41.1) · `services/preset_io.py` 312 (41.1) ·
`services/db_registry.py` 302 (41.1, **coverage 70.7%**) ·
`stores/history_repo_media.py` 302 (55.3) · `stores/media_fetch.py` 464 (31.5) ·
`stores/history_repo_lifecycle.py` 441 (37.7) · `stores/history_schema_repair.py`
441 (41.8) · `stores/history_repo_append.py` 366 (43.0) ·
`stores/history_repo_identity.py` 365 (44.1) · `services/collector_tick.py` 425
(33.0) · `services/window_preset_service.py` 326 (30.6) · `services/run/progress.py` 314 (31.0).

## 3. Steps

### H-C1 — the run family (one coherent step)

`services/run/` is five files and five mixins composed into one run ladder, and
it holds three of the area's worst cohesion scores. Decompose **by phase**, which
is the vocabulary the ladder already uses (`_begin_run` → `_prepare_cycle_queue`
→ `_execute_cycle` → per-user execution → `_finish_signals`):

* `RunCoordinator` (0.97, 17 methods) → orchestrator + named phase collaborators;
  the phases `_prepare_cycle_queue`/`_prepare_user_queue`/`_execute_one_queued_user`/
  `_finalize_user_status` are four candidates that already read as separate jobs.
* `RunQueueMixin` (0.94, 227 LOC) → label filtering (`filter_by_labels`,
  `_label_reason_for`, `_announce_label_skips`, `label_allows`) and queue
  ordering (`queue_order`, `_order_queue_by_column`) are separate concerns from
  single-target execution (`_run_single_target_cycle` 18, `_single_target_guard`,
  `_take_one_block` 19).
* `RunExecutionMixin` (0.88) and `RunLifecycleMixin` (0.89) are the retry/step
  policy and the lifecycle/signal policy — split by policy, not by size.

Target: no class in `services/run/` over 15 methods; each file ≤ 300 lines;
failure/stop paths covered (RULE 7 — every loop honours stop).

### H-C2 — the undo family

* `UndoService` (178 LOC, **28 methods, 86% delegations**) → keep it the facade
  it already is and **cut it to ≤ 15 methods**, moving the raw handlers into the
  existing sibling modules (`undo_apply`, `undo_archive`, `undo_db`,
  `undo_history`, `undo_timeline`, `undo_world`) rather than creating a new
  namespace.
* `services/history/mutate.py` (MI 34.9) → split by operation: settings/gaze
  (app-settings persistence) vs legacy import vs world/undo entry writes.
* `bridge/undo_bridge.py` (165/15/0.86) is Area B's file and pairs with this one:
  **`UndoService`'s public methods (`push`, `undo`, `redo`, `apply_command`,
  `attach`, `rewind_after_failure`) are a frozen interface this round.**

### H-C3 — the DB/world family

* `services/db_lifecycle.py` (328, `DbLifecycle` 276/22/0.88) — create/load/
  delete/clean/restore are five named operations; `_clean_unlocked` (42 LOC) is
  the worst.
* `services/db_registry.py` (302, `DbRegistry` 212/14, **coverage 70.7%**) —
  registry bookkeeping (`resolve`, `_prune_remembered`, `known_paths`) vs
  inventory reporting (`deletion_inventory_sources`, `existing_worlds`, `list_dbs`,
  `info` 32). Coverage first: the reporting half is barely exercised.
* `stores/history_db.py` (`HistoryDB` 232/30/0.86) — the write lane is the
  §16.5 landmine; the AREA-B/RULE 16 notes in `stores/world_lock.py` and the
  write-gate tests (`tests/test_world_write_gate.py`, 826 lines) pin its
  behaviour. **Split only what the pinned tests prove unchanged**, or leave it
  for a round with its own design; do not touch `WriteTurn`.

### H-C4 — the store planners (§2d)

Four extractions, each named for a real concept, each ≤ 200 lines:
`SchemaMigrator` → the legacy rebuild; `PersonLifecycle` → the soft-delete /
restore row ladder (`_restore_rows`, `_restore_one_row`, `_after_write` 40);
`AppendPlanner` → the prepend/empty-slot planner (`_prepend` 42, `_plan_prepend`,
`_take_empty_slot` 27, `_empty_slot_rows`); `MediaFetcher` → the network-body
finisher (`_fetch_via_network` 30, `_finish_network_body` 27, `_download`,
`_file_bytes`) beside the existing `_NetworkWatch`.

### H-C5 — the dense files (§2c)

Extract **named predicates and helpers** rather than files (RULE 19 step 3:
*"name the compound"*):

* `window_preset_service.py` — MI 30.6 with only a 27-LOC class: the logic lives
  at module level; name the validation/clamping/defaults steps.
* `run/progress.py`, `services/collector_tick.py`, `app/window.py`,
  `services/history/mutate.py`, `stores/label_assignments.py` — one named
  helper per repeated decision.

Target: MI ≥ 50 on each file listed in §2c, with no public signature change
(owner decision D3).

### H-C6 — write the facade verdict down

A short section — in this document plus the round's closing report — listing
`HistoryRepo`, `UndoService`, `Collector`, `HistoryExportService`, `MediaStore`,
`LabelStore`, `ScrollParser` with their delegation share (57–86%). The point is
that the *next* round does not spend a branch re-deriving it.

## 4. Rejected alternatives

| Rejected | Why |
|---|---|
| Split the facades to "fix" LCOM | Measured: 73–86% of their methods are one-line delegations; the LCOM score describes the pattern, not confusion. |
| Decompose the store planners by size (three ~130-line chunks each) | §16.1.1 — a helper must be named for a responsibility. The four concepts in H-C4 are named. |
| Split `stores/history_db.py` first because it is 0.86 | It holds the write gate; §16.5 requires a design doc and pinned behaviour, and Area D's mutation/coverage work should come first. |
| Touch `services/bot_*` (the newest feature) | 9 files, 68–299 lines, all inside the ideals; the defect round already split the bridge it forced over budget. |

## 5. Verification battery (every step)

```bash
.venv/bin/python tools/metrics/current_audit.py > /tmp/audit_c.json       # LCOM/MI per class
.venv/bin/python tools/metrics/stores_modules.py                          # §18.3 module counting still passes
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
```

Store splits also re-run `tools/metrics/stores_api.py`'s contract test
(`tests/unit/stores/test_stores_public_api.py`) and, while the AREA-B golden
exists, keep `dump_public_api` unaffected (it covers `backend`/`actions` only).

## 6. Cross-area notes

* **Frozen interfaces to Area B:** `HistoryQuery`'s public methods,
  `HistoryQueryService`/store API used by `bridge/history_bridge.py`, and
  `UndoService`'s public methods. This area changes no signature those files call.
* `actions/click_user.py::ClickUser` (225/14/0.93) is an *action block*: its wide
  `__init__` (13 params) is a RULE 3 block-settings constraint documented with a
  `quality-override` comment. The cohesion work is inside `execute`, not in the
  constructor.
* `tools/metrics/rule16_gate.py` rows for this area are edited here, in the
  renaming commit; the `OWNED` rows for `actions/speed.py`,
  `services/run/run_lifecycle.py::_resolve_run_speed` and `actions/base.py`
  must keep passing (they are covered by the speed-multiplier feature tests).
