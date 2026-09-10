# `_delete_unlocked` decomposition — design (max-CC regression fix)

Date: 2026-09-10. Scope: **one regression only** — the post-fixes audit
(`reports/CODE_QUALITY_METRICS_2026-09-10.md`, snapshot `24ea696`) found
`DbLifecycle._delete_unlocked` at **Radon CC 143 / cognitive 198 / nesting 7 /
631 LOC**, setting every global complexity maximum in the project (previous
project max CC 31).

Status: implemented, full suite green, metrics re-measured — see §4–5.

## 1. Problem

`services/db_lifecycle.py:158 _delete_unlocked` is one function implementing
seven sequential phases — validate → scan → switch → detach → database
(revalidate + unlink group) → media → finalize — with 27 separate
`DeletionOutcome` construction sites, each repeating ~10 keyword arguments.
The function:

- holds the project max for cyclomatic complexity (**143**, threshold ≤ 10),
  cognitive complexity (**198**, threshold ≤ 15), nesting (**7**, threshold
  ≤ 4) and function length (**631 LOC**, threshold ≤ 30);
- drags file Maintainability Index to **7.43** (project floor; audit target
  for this file: > 20);
- sits on the **only irreversible code path in the product** (permanent
  unlink), so the change must be behavior-preserving, not a rewrite.

Root cause is structural: fail-closed phases encoded as ~15 early
`return DeletionOutcome(...).as_dict()` blocks inside one function. Each
early return is an `if` plus a 12-line literal; all seven phases share the
same local state (`world_changed`, `plan_retained`, `removed`, …), which is
why it grew into one 631-line body instead of being split ad hoc.

## 2. Frozen contract (must not change)

Verified by reading all 19 files in `tests/integration/safety_deletion/`
plus `tests/test_db_manager.py` and
`tests/integration/services/test_db_manager_contract.py`:

1. **Result dict shape** — every outcome is still produced by
   `services.db_deletion.DeletionOutcome(...).as_dict()` with the same
   fields and values: `ok / op / path / was_active / before_path /
   media_files_removed / phase / partial / world_changed / active_path /
   removed_paths / retained_paths / failed_paths` (+ `error` when non-empty,
   + `last_database` / `unverifiable_worlds` extras). No key added, removed,
   renamed or retyped.
2. **Phase strings and error texts** unchanged (tests assert on them):
   `validate`, `scan`, `switch`, `detach`, `database`, `media`,
   `finalize`; messages incl. `"that database does not exist"`,
   `"cannot delete the last database — create a new one first"`,
   `"the database file is in use: …"`,
   `"some media files could not be removed; database deleted, media partially cleaned"`,
   `"deletion completed but final bookkeeping failed: …"`, etc.
3. **Fail-closed ordering** — no `os.unlink` before scan + plan + switch +
   detach + revalidate; DB group removed main-first and **stops at the first
   group failure** (remaining group members and all media preserved); media
   removed per-file (never `rmtree`); symlinks retained; empty-dir pruning
   stays bounded by `prune_empty_dirs`.
4. **Cancellation semantics** — `CancelledError` before the irreversible
   boundary propagates untouched; after irreversible work started, best
   effort `_forget` + `_persist_path` reconcile runs (each independently
   swallowed), warning logged, then the exception is re-raised.
5. **Patch points used by tests** (must remain effective):
   - `mock.patch.object(delmod, "build_deletion_inventory", ...)` where
     `delmod = services.db_deletion` (stale-plan test) → the flow must look
     the function up as a **module attribute**
     (`db_deletion.build_deletion_inventory(...)`), never bind it via
     `from services.db_deletion import build_deletion_inventory`;
   - `mock.patch.object(mgr.lifecycle, "_load_unlocked", ...)` and
     `mgr.lifecycle.load` → switch phase calls `self._lifecycle._load_unlocked(...)`;
   - `mock.patch("os.unlink", ...)` → unlinks stay direct `os.unlink` calls
     (the code deliberately does not use the `unlink_one` wrapper, for
     exact fault-injection parity).
   - `cfg.save` / `cfg.set_state` raising → finalize must return a truthful
     partial dict, never raise.
6. Public `DbManager`/`DbBridge` API untouched; `DbLifecycle.delete` still
   goes through `_guarded` (global + local locks).

## 3. New structure

Two new leaf modules, using **module-level functions rather than classes**
(mirroring Area C's `services/run/cycle_plan.py`). RULE 16 §1 hard-fails a
*new* class above 150 LOC / 15 methods and a *new* function above 4
parameters; the phases share ~18 per-run values, which a dataclass carries
explicitly (RULE 16 §1.2 prescribes "fold extras into a typed config
object" rather than wide signatures).

**`services/db_deletion_flow.py`** — mutating phases:

```
_DeleteState (dataclass, 24 LOC)  per-run mutable state incl. registry ref:
    path, registry, target, target_abs, was_active, world_changed,
    plan, plan_retained, base_abs, victim_folder_abs, folder_exclusive,
    other_folders, keep, footprint, outside_refs, keep_snapshot,
    inventory_snapshot, removed[], failed[], media_removed[],
    irreversible_started

_Fail (frozen dataclass, 9 LOC)   optional failure-outcome overrides
                                 (partial, media_count, extra, path, …);
                                 a plain refusal passes nothing
_PhaseRefusal(Exception, 6 LOC)  carries a finished DeletionOutcome dict;
                                 raised by raise_refusal(), caught once

shared helpers (module fns)       observed_active, raise_refusal,
                                 lexists, abspath_or_none, same_canonical

async delete_world(lifecycle, path) -> dict   orchestrator (only public fn)

phase functions (one small function per named step):
    _validate + _existing_abspaths
    _switch
    _detach (+ _detach_service_db, _close_memory)
    _revalidate (+ _rescan_keep, _reject_new_sharing)
    _remove_database_group
    _remove_media (+ _prune_dirs, _prune_victim_folder)
    _finalize (+ _finalize_media_partial, _success_outcome, _reconcile,
               _cancel_reconcile)
```

**`services/db_deletion_scan.py`** — the read-only phase 2 (mutates no
world state; this is the natural read/mutate seam, matching the old code's
own "BEFORE any switch/unlink" section):

```
async run_scan(st)               straight-line over the six scan steps
_scan_inventory(st)             other worlds enumerable; victim in union
_scan_victim(st)                strict victim media scan
_scan_other_worlds(st, inv)     keep set; refuses on unverifiable world
_resolve_footprint(st, scan)    in-base footprint vs retained refs
_resolve_folder_policy(st, inv) other folders + exclusivity
_discover_media_files(st)       bounded walk of the exclusive folder
_build_plan(st, inv)            path policy + stale-plan snapshots
```

`DbLifecycle._delete_unlocked` becomes a thin delegate (917 → 303 LOC
file; class 883 → 269 LOC):

```python
async def _delete_unlocked(self, path: str) -> dict:
    from services.db_deletion_flow import delete_world
    return await delete_world(self, path)
```

The import is function-local to keep the flow ↔ scanner edge
one-directional: `db_deletion_scan` imports `_DeleteState` / `raise_refusal`
/ guards from `db_deletion_flow` at module load, and `delete_world` imports
`run_scan` lazily — no import cycle. Both modules only depend on the
stdlib, `services.db_deletion` and `services.db_media_scan`.

### 3.1 Why an internal `_PhaseRefusal` exception

The ~27 outcome sites share the shape "stop the phase pipeline now and
return this dict". Encoding each as `result = ...; if result: return result`
would add a branch per phase to every caller (7 × `if` in the orchestrator)
and scatter the return shape. A narrow internal exception — caught **once**
in `delete_world` — is the standard fail-closed pattern (analogous to an
HTTP 4xx raised in a handler): phases read top-to-bottom as the pipeline,
and `asyncio.CancelledError` (a `BaseException` on 3.8+) can never be
swallowed by `except _PhaseRefusal`. It carries an already-rendered dict,
so the external behavior is exactly "early return".

### 3.2 Why state / failure dataclasses instead of more arguments

The phases share ~18 values; threading them as function arguments would
create exactly the wide signatures RULE 16 §1 rejects (and which the audit
already flags elsewhere, max 20 params). A per-run `_DeleteState` dataclass
keeps every phase function at 1–3 parameters and makes the mutation points
(`world_changed`, list accumulations) explicit. Likewise the handful of
failure outcomes that need non-standard fields (partial, media_count,
extras, validate-time path) take one small frozen `_Fail` typed options
object instead of 10 keyword-only parameters; a plain refusal needs no
options at all.

### 3.3 Dead code removed during the move (no behavior change)

- unused `unlink_one` import (the audit's new Vulture finding; direct
  `os.unlink` is required by tests) — it simply is not re-imported;
- `scan_details` list in the other-world scan loop: appended to, never read;
- the empty `try: pass finally: pass` in the DB-group `OSError` handler;
- the always-true placeholder
  `if not plan_keep_snapshot.issuperset(frozenset(a for … if … or True)): pass`
  (the generator predicate is `… or True` → body provably unreachable; the
  real new-sharing check right below it is preserved verbatim).

Nothing else changes semantics. In particular every defensive
`try/except` around `os.path` calls and every refusal ordering is
transcribed 1:1.

## 4. Complexity budget — measured after the split

Measured with the audit's own tooling (Radon 6.0.1, cognitive-complexity
1.3.0, the §2 nesting walker in `tools/metrics/current_audit.py`); Radon's
counting is base 1; +1 per `if`/`for`/`except`/`and`/`or`/
comprehension-`if`.

| | gate | `db_deletion_flow.py` | `db_deletion_scan.py` |
|---|---|---:|---:|
| functions | — | 25 | 8 |
| max CC | ≤ 10 | **10** | **9** |
| max cognitive | ≤ 15 | **12** | **11** |
| max nesting | ≤ 4 | **4** | **3** |
| max function LOC | ≤ 30 | **24** | **27** |
| max params (excl. self) | ≤ 4 | **4** | **2** |
| application classes | ≤ 150 LOC / ≤ 15 methods | only dataclasses ≤ 24 LOC | none |
| file MI | > 20 | **31.50** | **53.76** |

The scan phase is split into six steps because the honest floor for one
function doing inventory + victim scan + other-world scans + footprint +
exclusivity + planning is ~25 CC — that is real branching, not metric
scaffolding, and each step is a named safety concept already present in
the old code.

### Project-wide, this checkout before → after (`current_audit.py`)

| Metric | before | after |
|---|---:|---:|
| Max Radon CC | **143** `_delete_unlocked` | **42** (`build_deletion_inventory`, Phase-4 tail) |
| Max cognitive | **198** | **55** |
| Max nesting | **7** | **6** |
| Max function LOC | **631** | **124** |
| functions CC > 10 | 74 | **73** |
| functions > 30 LOC | 84 | **83** |
| mean CC | 3.45 | 3.40 |
| mean cognitive | 2.65 | 2.57 |
| classes > 300 LOC | 12 | **11** (`DbLifecycle` 883 → 269 LOC) |
| exact clone groups / lines | 4 / 66 | 4 / 66 |
| `db_lifecycle.py` MI | **7.43** | **41.25** |
| Vulture findings ≥ 90% | 8 | **7** (dead `unlink_one` import gone) |

The remaining global maxima (CC 42 / cognitive 55 / nesting 6 / 124 LOC)
all belong to the audit's Phase-4 tail (`build_deletion_inventory`,
`scan_world_media`, `classify_candidate`, …) which this task explicitly
excluded; nothing extracted from `_delete_unlocked` exceeds a gate.

## 5. Verification — executed

1. Before touching code: `tests/integration/safety_deletion/` (129),
   `tests/test_db_manager.py` +
   `tests/integration/services/test_db_manager_contract.py` (64) green.
2. After the move: the same **193 tests green with zero test edits**, then
   the **full suite: 2,467 passed, 0 failed**, 3 skipped, 1 deselected,
   1 xfailed, 771 subtests (the one remaining runtime warning is the
   pre-existing unawaited `handle_push` from the audit — unchanged).
3. JS: all 20 `tests/test_*.js` entrypoints pass under Node.
4. RULE 16 §3: all 33 new functions are executed by the suite (0 wholly
   uncovered new functions). Project coverage stays above both floors:
   **90.23% line / 84.18% branch**. Apples-to-apples on the deletion
   suites (same 193 tests before and after): the touched code went
   383/552 statements (69.4%) → 483/626 (77.2%) across the three modules.
   Under the full suite, uncovered branch destinations in the deletion
   code are 35 across the new modules vs 34 in the old single file; every
   remaining gap is a pre-existing defensive path (no-fallback,
   service-None, incomplete re-scan, empty new-sharing, post-unlink
   cancel) that audit Phase 2 already schedules for fault-injection
   tests — no previously covered behavior lost.
5. No test file modified (contract pin).

## 6. Explicitly out of scope

- `build_deletion_inventory` (CC 42), `scan_world_media` (29),
  `classify_candidate` (28), `deletion_inventory_sources` (23),
  `prune_empty_dirs` (20) — audit Phase 4 tail, untouched here;
- coverage of `db_lifecycle.py` (audit Phase 2 test work) — no new tests
  required for this structural fix, behavior is pinned by existing tests;
- class-shape / LCOM work (audit Phase 7).
