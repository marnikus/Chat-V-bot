# Round plan — god classes & oversized modules (RULE 19 step 4)

Measured 2026-09-12 on `arena/01a094dc-chat-v-bot`, after the complexity
rounds already landed. This is the *plan*; the step-1 execution and its
before/after numbers are in
[`STEP1_CHAT_SYNC_DESIGN_2026-09-12.md`](STEP1_CHAT_SYNC_DESIGN_2026-09-12.md).

## Why this round

The complexity gates are green. Re-measuring the whole tree (same
`tools/metrics/current_audit.py` runner, same frozen definitions as
`reports/CODE_QUALITY_METRICS_2026-09-10.md`) gives:

| Gate | Fail line | Current | Verdict |
|---|---|---:|---|
| Cyclomatic complexity | > 10 | **0** functions over | green |
| Cognitive complexity | > 15 | **2** functions over | 2 legacy outliers |
| Nesting depth | > 4 | **0** functions over | green |

RULE 19 fixes **nesting → CC → cognitive → size** in that order. Steps 1–3 are
now effectively done, so this round is **step 4 — size** (RULE 18 §18.2/§18.3),
which the earlier reports already flagged as "known debt, do not grow":

> "the **10 files still over 500** are listed there. They are known debt
> (§16.5 landmines): do not grow them, extract from them when you next touch
> them." — `reports/IDEAL_SIZE_BASELINE_2026-09-11.md` §2

The single worst file — by a wide margin — is `backend/chat_sync.py`:
**791 LOC, Maintainability Index 10.8** (next-worst file is 16.1). That is the
biggest problem, so it is step 1.

## The problem, ordered

Priority = (size debt × risk × reach). Ordered worst-first:

| # | Target | LOC | MI | Class / methods | LCOM* |
|---|---|---:|---:|---|---:|
| 1 | `backend/chat_sync.py` | 791 | **10.8** | `SyncSession` / 24 | 0.90 |
| 2 | `services/db_deletion.py` (+ `db_deletion_flow.py` 509) | 665 | 20.5 | module family | — |
| 3 | `backend/scroll_parser.py` | 674 | 28.4 | `ScrollParser` / 37 | 0.87 |
| 4 | `services/collector_service.py` | 593 | 27.0 | `Collector` / 39 | **0.93** |
| 5 | `backend/history_query.py` | 606 | 33.5 | `HistoryQuery` / 14 | 0.74 |
| 6 | `bridge/history_bridge.py` + `bridge/stack_bridge.py` | 537+308 | 23.5 | `HistoryBridge`/31, `StackBridge`/31 | 0.87/0.89 |
| 7 | `services/undo_service.py` | 564 | 23.3 | `UndoService` / 27 | 0.92 |
| 8 | `backend/config_manager.py`, `dom_highlight.py`, `message_injector.py`, `media_handler.py` | 502/523/478/478 | 40.5/54.9/41.8/45.2 | module family | — |

LCOM* is Henderson–Sellers; ≥ 0.5 means the methods share little state, i.e.
the class is a candidate for a responsibility split. `Collector` at **0.93** is
the least-cohesive god class, but it is also a §16.5 landmine whose lifecycle
is pinned by the collector tests, so it is sequenced *after* the mechanical,
already-internally-split files.

## The 8 steps (≈16 h each)

Each step follows the same discipline (RULE 16 §16.5/§16.6):

1. **Lock behaviour first** — characterization tests on the class/file before
   touching it (RULE 8: tests execute the real thing).
2. **Design the split** in this directory (RULE 16.6.2), recording the
   rejected dishonest reductions.
3. **Extract by single responsibility** (RULE 18 §18.2 / RULE 19 §19.4),
   following the `services/run/` sub-package precedent.
4. **Gate**: `radon cc -s`, then `tools/metrics/rule16_gate.py`; suite green.

| Step | Do | Outcome metric (target) |
|---|---|---|
| **1** ✅ | Split `backend/chat_sync.py` → `backend/chat_sync/` (10 modules) | file 791 → ≤278, MI 10.8 → ≥39.9 |
| **2** | Split `services/db_deletion.py` + `db_deletion_flow.py` → `services/db_deletion/` | 665+509 → ≤300 each |
| **3** ✅ | Extract `ScrollParser` (probe / parse / settle) | class 507/37 → ≤150/≤15 |
| **4** | Extract `Collector` (lifecycle / tick-sync / push) | class 518/39 → ≤150/≤15 |
| **5** ✅ | Split `backend/history_query.py` beside the `history_repo*` family | file 606 → ≤300 |
| **6** | Split the bridge facades (`HistoryBridge`, `StackBridge`) per surface | class 474/31 → ≤150/≤15 |
| **7** | Extract `UndoService` (undo / redo / world-sync / archive) | class 409/27 → ≤150/≤15 |
| **8** | Split the remaining 400–530 LOC backend modules | files > 500 → **0** |

Success of the round: **no file over 500 LOC** and **no class over 150 LOC /
15 methods** outside the documented §16.4 compat facades, with the suite and
coverage floors (≥ 80% line / ≥ 75% branch) intact.

## Residual complexity (not this round's target)

Two legacy functions still exceed cognitive 15 (RULE 16 §16.2): they are
pre-existing and may not *worsen* (§16.5); they are not size debt and are
tracked separately:

* `bridge/router.py` `_build_router_class` — cognitive 17 (a long-and-flat
  metaclass builder; RULE 19.5, extract per phase, not per branch).
* `stores/settings_store.py` `get` — cognitive 17, nesting 4 (the defaults
  fall-back walk; extract a `_from_defaults` helper).

They are cheap and can be closed inside any step's verification pass without
derailing that step's size work.
