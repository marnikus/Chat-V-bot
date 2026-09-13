# Step 1 — split `backend/chat_sync.py` into a sub-package

Done 2026-09-12. The target was the single worst file in the tree:
`backend/chat_sync.py`, **791 LOC, Maintainability Index 10.8** (the next-worst
file was 16.1 — an outlier by a factor of ~1.5).

## Why this file, first

RULE 19 orders remediation nesting → CC → cognitive → **size last**. The tree
is now green on steps 1–3 (0 functions over CC 10, 0 over nesting 4, only 2
legacy cognitive outliers in `bridge/`/`stores/`), so size is the frontier.
`chat_sync.py` is the frontier's worst point, and it is *already* internally
split into named phases — the work is mechanical, low-risk, and behaviour
-preserving, which is exactly what a first step should be.

## What was already there (the design was honest)

The module docstring already named the phases, and the code already held them
as separate classes with string-typed cross-references — the file just never
got the sub-package promotion that RULE 18 §18.3 prescribes for a family that
outgrows a single module (the same promotion `services/run/` received):

```
SyncOptions   SyncPlanner   SyncPersister   ChunkReader   DeltaAligner
ReadPlan      merge_live    SyncSession     run_sync
```

## The split (one responsibility per module, imports flow top-down)

| Module | Owns | LOC |
|---|---:|---:|
| `constants.py` | `SLICE_RETRIES`, `MODE_*`, `_MAX_QUIET_RETRIES` (pure data) | 21 |
| `options.py` | `SyncOptions` (the immutable knobs) | 90 |
| `plan.py` | `ReadPlan` + `SyncPlanner` (the pure decision) | 144 |
| `merge.py` | `merge_live` (fold an AppendResult into the live result) | 30 |
| `persister.py` | `SyncPersister` (every repo.write in one place) | 153 |
| `reader.py` | `ChunkReader` (paced, retrying range reads) | 90 |
| `aligner.py` | `DeltaAligner` (overlap with the stored tail) | 43 |
| `session.py` | `SyncSession` (the mutable shared state + phases) | 278 |
| `sync.py` | `run_sync` (the orchestrator) | 46 |
| `__init__.py` | the frozen public seam (re-exports) | 60 |

No module is over 300 LOC; `session.py` (278) is inside the RULE 18 §18.2
ideal band (150–300) and stays a single responsibility — the mutable
`SyncSession` that the phases share. The import order is a DAG: `constants →
options → plan → merge`, with `persister`/`reader`/`aligner` as leaves that
reference `SyncSession` only in string type hints (so they never import
`session` back, exactly as before).

## The frozen seam

`backend/chat_parser.py` and the sync tests import these names from
`backend.chat_sync`, so `__init__.py` re-exports them verbatim — the call
surface did not move (RULE 18 §18.2: a split must not change the callers):

```python
run_sync, SyncOptions, merge_live, SLICE_RETRIES            # chat_parser
SyncPersister, SyncSession                                  # test_chat_sync_phases
MODE_EMPTY, MODE_UNCHANGED, MODE_DELTA, MODE_FULL,
SyncOptions, SyncPlanner                                    # test_chat_sync_plan
```

`backend.chat_parser.sync_conversation()` keeps its exact 14-parameter
signature and still delegates to `run_sync()` — no caller changed.

## Before → after (same frozen audit runner)

| Metric | Before | After |
|---|---:|---:|
| File size | 791 LOC | 21–278 LOC (10 files) |
| Maintainability Index (file) | **10.8** | worst **39.9** (`session.py`) |
| Mean MI (whole tree) | 64.45 | **65.49** |
| Files over 500 LOC (tree) | 10 | **9** |
| Functions over CC 10 | 0 | 0 (unchanged) |
| Functions (tree) | 1992 | 1992 (no net change) |

## Honest reductions rejected (RULE 16 §16.2)

* Did **not** merge the two small pure modules (`constants`, `merge`) into
  `plan`/`session` to hit a file-count target — they hold distinct
  responsibilities and `merge_live` is re-exported by the façade.
* Did **not** split `SyncSession` further to get `session.py` under 150: the
  class is one responsibility (the shared state), and splitting it would be a
  line-quota split (the anti-pattern RULE 19 §19.4 names).
* Did **not** change a single function body — the 1992-function count is
  unchanged because the step is a *relocation*, and relocation must be
  provably behaviour-preserving.

## Verification

* `tests/unit/backend/test_chat_sync_plan.py` — 25 tests pass.
* `tests/unit/backend/test_chat_sync_phases.py` — 31 tests pass.
* Full suite + coverage run: see the round report
  [`reports/CODE_QUALITY_METRICS_2026-09-12.md`](../../../reports/CODE_QUALITY_METRICS_2026-09-12.md).
* `radon cc -s backend/chat_sync/` — every function CC ≤ 9 (worst:
  `SyncPersister.repair_tail`, `SyncSession._prepare_viewport`,
  `DeltaAligner.split`, all B(9)).
* `tools/metrics/rule16_gate.py` — "All owned functions fit. Ratchet intact.
  No stale overrides."
