# Facade verdict — Area C (H-C6)

Round H 2026-09-14 · Area C owns services/**, stores/**, actions/**, app/**

## Measured evidence — do not split these

| Class | File | LCOM* | LOC | Methods | ≤3 LOC delegations | Verdict |
|---|---:|---:|---:|---:|---:|---|
| `HistoryRepo` | `stores/history_repo.py` | 0.89 | 225 | 44 | **86%** | Facade over 11 prefix families (`history_repo_*`, `history_db`, `history_schema*`). Shim + 11 files pattern established in B2. Splitting reproduces same shape one level down, breaks every caller. Keep. |
| `UndoService` | `services/undo_service.py` | 0.95 (now 0.94 with 7 direct) | 178 → 93 | 28 → 7 | **86%** | Timeline facade over `undo_history`, `undo_apply`, `undo_db`, `undo_world`, `undo_archive`, `undo_timeline`. H-C2 cut direct methods 28→7 via delegate mixins. Keep facade. |
| `Collector` | `services/collector_service.py` | 0.95 | 216 | 40 | **85%** | Orchestrator over `collector_*` (probe, archive, loop, push, report, partner). Heartbeat state machine. Keep. |
| `HistoryExportService` | `services/history/export.py` | 0.99 | 80 | 14 | 79% | Export router over query/mutate. Small, delegation-heavy. Keep. |
| `MediaStore` | `stores/media_store.py` | 0.93 | 214 | 33 | 73% | Facade over `media_fetch`, `media_cache`, `media_layout`. Media cache API. Keep. |
| `LabelStore` | `stores/label_store.py` | 0.89 | 222 | 38 | ~70% | Facade over `label_*` (rules, assignments, filter, world, state). Keep. |
| `ScrollParser` | `backend/scroll_parser.py` | 0.91 | 108 | 14 | 57% | Facade over `scroll_parser_*` (dom, judge, loop, model). Area B file but same pattern. Keep. |

## Why LCOM lies here

LCOM* measures field overlap across methods. A router that holds 5 collaborators
and has 30 one-line delegators (`return self._x.foo()`) will have near-zero
overlap — each delegator touches a different field — so LCOM → 1. The score
describes the pattern (delegation), not confusion. Splitting such a router
creates N new routers with same shape.

## What was done instead (H-C2, H-C4)

- `UndoService`: cut direct methods 28→7, moved delegators to 4 mixins
  (`undo_*_delegates.py`), LCOM still high but method count ≤15 (target).
- `HistoryRepo`: already split into 11 files (`history_repo_append`,
  `history_repo_identity`, `history_repo_lifecycle`, etc.) plus helpers
  (`history_repo_restore`, `history_repo_slots`, `history_schema_legacy`).
  Each helper ≤200 LOC, named by responsibility (H-C4).
- `Collector`: heartbeat split into `collector_probe` (140) and
  `collector_archive` (187), facade `collector_tick` 59 LOC (H-C4).
- `MediaStore`: `media_fetch` 464→265, `media_network` 148 extracted (H-C4).

## Frozen interfaces to Area B

- `HistoryQuery` public methods (used by `bridge/history_bridge.py`)
- `UndoService` public: `push`, `undo`, `redo`, `apply_command`, `attach`,
  `rewind_after_failure` — frozen this round
- `HistoryRepo` public API used by `services/history/*` and `bridge/*`

Next round must not re-derive facade split; this doc is the record.
