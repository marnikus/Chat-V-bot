# AREA C follow-up — design for the remaining CC 9 in `_execute_cycle`

Date: 2026-09-10. Scope: AREA C only. Status: **implemented, verified, committed**
(single follow-up commit on the session branch; table below shows measured
radon values, not predictions).

`_execute_cycle` went CC 31 → 9 in C2 and already meets the master-plan aim
(CC ≤10). This doc designs the honest path from 9 → 5 (grade A). The core
insight from research: **5 of the 9 points are dead red-phase scaffolding**,
not real decisions. The reduction is dead-code deletion plus one extraction
that mirrors an established C1/C2 pattern — not metric-gaming.

Master-plan constraint (frozen): *"Do not scatter conditions into meaningless
one-line helpers to satisfy a metric."* Every step below is justified on
readability grounds first; the CC drop is a side effect.

## 1. Research findings

### 1.1 Exact branch inventory of the 9

Radon counting rules were verified empirically on scratch snippets: base 1,
+1 per `except` handler, +1 per `if`, +1 per `and`/`or`, +1 per ternary or
comprehension-`if`; `try` itself and `in`-tests cost nothing.

`_execute_cycle` today (`services/run/coordinator.py`):

| # | Construct | Cost | Honest? |
|---|-----------|------|---------|
| 0 | base | 1 | — |
| 1 | `except ImportError` (lazy `RunStopped` import) | +1 | **No — dead.** Module exists since C1; the `pragma: no cover` guard never fires. |
| 2 | `except asyncio.CancelledError: raise` | +1 | Defensive; redundant next to a *narrow* handler (`except RunStopped` never catches it). |
| 3 | `except Exception` + `if RunStopped is not None and isinstance(...)` | +3 | **No — scaffolding.** Exists only because the import is `Optional`-typed. A direct import collapses all three into `except RunStopped` (+1). |
| 4–6 | three mode dispatches (`stopped` / `single_target` / `empty`-family) | +3 | **Yes — intrinsic.** Six outcomes need three binary decisions. |

9 = 1 base + 5 scaffolding + 3 intrinsic. The principled floor for an honest
orchestrator here is **5** (1 base + 4 independent binary decisions); §4
proves going below 5 requires merging decisions dishonestly.

### 1.2 Import-graph findings (decide top-level vs lazy imports)

- `actions/cancellation.py` is a **stdlib-only leaf** (`asyncio`, `time`,
  `typing`). No code under `actions/` imports `services.run.*` (one comment
  mention only) → no import cycle in either direction.
- BUT `actions/__init__.py` runs `ActionRegistry.scan()` on package import,
  which imports all 21 action modules. Verified empirically:
  - `import services.run` today loads **zero** `actions.*` modules (light
    path is clean — the pure `cycle_plan` unit tests depend on this);
  - `from services.run.coordinator import RunCoordinator` loads 21
    (coordinator already does `from actions.base_action import ...` at top).
- Consequence:
  - **coordinator.py** may take a top-level
    `from actions.cancellation import ...` — zero new import-time cost.
  - **progress.py / error_recovery.py must stay function-lazy**, but the
    `try/except ImportError` wrapper can go: a plain function-local
    `from actions.cancellation import ...` costs **0 CC** and defers the
    scan to first engine use, preserving today's import-time behaviour.
- No external users of the three module-local `_is_stop_requested`
  wrappers (all call sites module-internal) → safe to delete.
- The suite treats a bare `RunStopped` as meaningful **without** the engine
  flag (`test_permissive_retry_still_cannot_retry_stop` raises it with no
  flag) → the exception carries stop identity, not the flag. Any design
  that *infers* stop from the flag contradicts the suite (§4, rejected D3).

## 2. Design

### Step 1 — Delete dead red-phase guards (all three run modules)

Mechanical transform, 15 `except ImportError` sites:

| File | Transform |
|------|-----------|
| `coordinator.py` | Top-level `from actions.cancellation import RunStopped, is_stop_requested, check_stopped`. Delete local `_is_stop_requested` def; rename its ~10 call sites (`sed s/_is_stop_requested(/is_stop_requested(/`). Delete `_raise_if_stopped` (identical to `check_stopped`); its 3 call sites in `_prepare_cycle_queue` become `check_stopped(self)`. |
| `progress.py`, `error_recovery.py` | Keep imports function-local (light path, §1.2) but unguarded: `try/except ImportError` → plain `from actions.cancellation import ...`. Delete local `_is_stop_requested` defs; call sites use the imported `is_stop_requested`. Every `if <pred> and RunStopped is not None: raise RunStopped` (+2: `if`+`and`) → `check_stopped(...)` (+0). Every `except Exception` + `if … and isinstance(exc, RunStopped)` (+3) → `except RunStopped` (+1). Delete the `pragma: no cover` `asyncio.sleep` fallback in `retry_with_backoff` (dead `else` branch). |

`_execute_cycle` after Step 1: 9 − 1 (guard) − 2 (`if`+`and`) = **6**
(base + `except CancelledError` + `except RunStopped` + 3 mode `if`s).

### Step 2 — Extract guarded prepare (coordinator.py only)

New helper (CC 2 = base + one narrow handler):

```python
async def _try_prepare_cycle_queue(self) -> tuple[list, bool] | None:
    """Collect→filter→order→take; None when a cooperative stop won.

    ``CancelledError`` propagates untouched: the handler below is narrow
    (``RunStopped`` derives from ``Exception``), so no explicit re-raise
    is needed. Unexpected exceptions propagate.
    """
    try:
        return await self._prepare_cycle_queue()
    except RunStopped:
        return None
```

This mirrors the established C1/C2 mapping pattern (`_execute_one_queued_user`
maps `RunStopped`→`"stop"`; single-target does the same) — precedent, not a
metric-driven one-off. Callers must test `is None` (an empty legitimate
queue `[]` is falsy but not `None`).

`_execute_cycle` after Step 2 (**CC 5**, grade A):

```python
async def _execute_cycle(self) -> str:
    prepared = await self._try_prepare_cycle_queue()
    if prepared is None:
        self._announce_stopped(); return "stopped"
    queue, take_matched = prepared
    facts = inspect_stack(self._stack)
    decision = choose_cycle_mode(facts, has_queue=bool(queue),
                                 take_matched=take_matched,
                                 stopped=is_stop_requested(self))
    if decision.mode == "stopped":
        self._announce_stopped(); return "stopped"
    if decision.mode == "single_target":
        return await self._run_single_target_cycle(facts.has_conditional_skip, take_matched)
    if decision.mode in ("empty", "empty_stack"):
        return self._announce_empty_mode(decision.reason, list(facts.user_scoped_ids))
    queue, standalone = self._prepare_user_queue(queue, decision.mode)
    return await self._run_user_queue(queue, facts.has_conditional_skip, standalone)
```

1 base + 4 `if`s = 5. **This is the floor**: four independent binary
decisions (prepare-stop, flag-stop, single-target, empty-family) cannot
honestly cost less than four branches.

### Measured radon delta

| Function | Before | After |
|----------|--------|-------|
| `_execute_cycle` | 9 B | **5 A** |
| `_try_prepare_cycle_queue` (new) | — | 2 A |
| `_execute_one_queued_user` | 6 B | 2 A (redundant explicit `CancelledError` re-raise dropped next to the narrow handler) |
| `_prepare_cycle_queue` | 5 A | 5 A (`_raise_if_stopped` deleted; remainder is the scroll-scan genexp + `?:` — honest) |
| `execute` | 39 E | 36 E (out of scope, noted only) |
| `_order_queue_by_column` | 17 C | 12 C |
| `_run_single_target_cycle` | 15 C | 11 C |
| `_run_take_phase` | 15 C | 8 B |
| `retry_with_backoff` | 14 C | 7 B |
| `_run_collect_phase` | 20 C | 17 C |
| `_execute_for_user` | 20 C | 18 C |
| `should_retry` | 6 B | 4 A |

## 3. Verification plan (no new tests)

Behaviour-preserving by construction; the existing suite is the equivalence
gate (C1 tests-before-refactor already lock every touched path):

1. Full run suites green: `tests/integration/run_safety/` +
   `tests/unit/services/test_cycle_plan.py` +
   `tests/unit/actions/test_wait_page_cancellation.py` +
   `tests/integration/services/test_run_state_machine_contract.py` (132 passed
   baseline) plus the 162-test engine regression set.
2. `radon cc` before/after on the three modules; `_execute_cycle` must read 5.
3. Import-time behaviour preserved: after `import services.run`, no
   `actions.*` in `sys.modules`; coordinator import still triggers the scan.
4. `grep -rn "except ImportError" services/run/` → empty;
   `grep -rn "RunStopped is not None" services/run/` → empty.

## 4. Considered and rejected

- **D3 — flag inference (CC 4).** Helper swallows `RunStopped`→`([], False)`
  and the table's `stopped=…` flag check carries the outcome. Saves one more
  point but relies on the undocumented cross-module invariant
  "`RunStopped` ⟺ flag set" (3 phases + wait_page). A future speculative
  raise would silently degrade `stopped`→`empty`; contradicts §1.2 (suite
  treats flagless `RunStopped` as meaningful). Rejected: readability-first,
  anti-gaming rule.
- **D0 — move cancellation helpers to `core/`.** Would allow top-level
  imports everywhere with zero scan coupling and is arguably the better
  layer long-term. Rejected *for now*: larger churn (new module + re-export
  shim + all import sites) for no additional CC gain over Steps 1–2.
  Revisit if a second cross-cutting leaf needs the same treatment.
- **Dispatch-table for the three mode `if`s.** Same branch count hidden
  behind lambdas/partials with mixed sync/async signatures — strictly less
  readable. Rejected.
- **Restructuring `execute` (39), `wait_page` (25), phase bodies.**
  Out of scope: lifecycle orchestration and per-block reporting are honest
  complexity; only the shared dead-guard sweep touches them.

## 5. Implementation sketch (when approved)

Single commit on the session branch: Steps 1–2 + verification §3. Estimated
diff ~120 lines changed across 3 files, net negative (~−40). No doc updates
beyond this file; no test changes (suite is the gate).
