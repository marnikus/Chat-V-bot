# Round 4, steps 6–7 — session lifecycle and final facade

Written 2026-09-13 on `arena/01a093f4-chat-v-bot`, continuing the existing
working tree. This is a behavior-preserving extraction, not an expansion of
cooperative-stop or failure-cleanup policy.

Queue: `docs/archive/2026-09-12-refactor-round4/ROUND4_DESIGN.md`.
Preceding results: `reports/REFACTOR_ROUND4_STEPS_4_5_2026-09-12.md`.
Rules: `docs/current/AGENT_RULES.md`, especially RULE 16/18/19 and RULE 15.

## 1. Research and baseline

`backend/chat_sync.py` is 337 lines. `SyncSession` is 248 lines with 24 direct
methods, mixing shared data, page admission, viewport recovery, and completion.
No method exceeds CC 10 or nesting 4: RULE 19's long-and-flat case applies.

| Existing method | LOC | CC | cognitive | nesting |
|---|---:|---:|---:|---:|
| `prepare` | 19 | 3 | 2 | 1 |
| `_pass_gate` | 21 | 6 | 7 | 2 |
| `_prepare_viewport` | 12 | 9 | 8 | 1 |
| `restore_viewport` | 20 | 5 | 4 | 1 |
| `finish` | 11 | 7 | 5 | 1 |
| `run_sync` | 25 | 5 | 4 | 1 |

`run_sync` has **five** parameters, including `**legacy`; this is an existing
frozen API, not permission to invent wide new functions. Preserve it verbatim
and document a params=5 override at the new definition. Gate that metric alone;
all its other metrics must still fit.

Baseline from preceding full validation: **2752 passed**, 3 skipped,
1 deselected, 1 xfailed; 774 subtests. Line **91.13710%**, branch **85.91084%**.
Reinstall measurement dependencies and build the repo's Qt import stubs, since
virtual environments are not persisted between turns.

## 2. Ownership and dependency design (before implementation)

Three new modules complete a seven-file sync package (including `__init__`):

* `backend/sync/session.py`: original dataclass fields/defaults/constructor,
  result aggregation and state-signature refresh; composition root for the
  persister, viewport and lifecycle. Owns `run_sync` after step 7.
* `backend/sync/lifecycle.py`: admission (`probe → install → private gate →
  viewport → cursor → plan`) and final result/cursor bookkeeping. A
  `SyncLifecycle` collaborator receives the shared session; no import of it.
* `backend/sync/viewport.py`: prepare/settle, emptied-pane recovery, read-window
  clamping and best-effort restoration. A `SyncViewport` collaborator receives
  the same session, without importing the session/facade.

Runtime dependencies flow from session to its phases, not back. The lazy
`backend.chat_parser.verify_private` import remains inside the admission gate:
that parser delegates to the facade, so an eager import would create a cycle.
No Qt, service or action-registry imports at module load. Phase methods access
only declared public session state and public collaborators/state-refresh API,
not one another's private methods.

The dataclass's **11 existing public/hook methods** are frozen by the backend
API snapshot. Keep its explicit public methods as small compatibility adapters
where responsibility moves, with no dynamic `__getattr__`, generated methods,
inheritance/mixins, or rewritten metadata. These adapters earn their place by
preserving the actual consumer API; new behavior lives on named collaborators,
not a collection of numbered helper methods. One public state refresh replaces
the old private `_sync_sigs` internal coupling. Target session <= 120 lines,
<= 15 hard method cap; explain the preferred 10-method deviation for the frozen
API. Collaborators target <= 120 lines / 10 methods each.

Step 7 then moves `run_sync` unchanged into session.py and reduces
`backend/chat_sync.py` to explicit re-exports and `__all__`. Preserve all prior
exports (including access to the already-imported `SyncResult` type), no wrapper
function or duplicate class. Remove the unused private `_MAX_QUIET_RETRIES`
constant rather than pretending it controls retries. No external caller edit
or public snapshot refresh should be needed.

## 3. Semantics that must not drift

Characterize these through real public calls **before** moving code:

1. A refused private gate performs no scrolling, archive lookup or write;
   a failed/reinstalled agent is distinct from an empty conversation.
2. Backfill ordering: probe/gate → scroll/settle → archive reads → chunks →
   viewport restoration → tail media repair → backfill marker/cursor/totals.
3. Settling failure falls back to a state probe; empty/non-dict fallbacks keep
   their current semantics. Restored counts/signatures clamp the retried range.
4. `old_top == 0` intentionally schedules no final restoration; no extra restore
   on empty/unchanged short-circuits. Do not silently add a finally block.
5. A restore failure is best-effort and logged; a cancellation propagates.
   A canceled/failing archive write must not manufacture final cursor success.
6. Partial/stopped/pending backfills never claim a complete tail or backfill;
   existing result reasons are not overwritten by `finish`.
7. Independent sessions share no mutable state or collaborators. Dataclass
   field defaults and argument order remain unchanged.

An in-flight CDP request still completes at its current await boundary on
cooperative stop. External cancellation still propagates. Broadening cleanup
on failure/cancel or making viewport settling independently stop-aware would
be a separate behavior change with a separate design, not part of these moves.

## 4. Staging and acceptance

A. Save pre-step source/audit. Add lifecycle/viewport characterization and run
it with the existing sync/API suites before changing production.
B. Implement three collaborating types; keep `run_sync` at its current path
until the extraction's focused tests pass (step 6).
C. Move orchestration last; prove its AST unchanged and every legacy export
identical to its implementation object (step 7). Fresh-process import checks
must catch facade/parser/registry cycles, and the facade must contain no logic.
D. Automatically enumerate all new functions/classes through the existing
RULE 16 engine. Check tools are present, hard limits fit, and the sole params
exception is documented and still exactly five. Record RULE 18 ideal deviations.
E. Run full Python branch coverage, old+new quality gates, clones, Vulture,
unused-import checks, Node harnesses, and unchanged API snapshots. Coverage
must not fall below the preceding slice. No zero-hit new functions. No new
clone groups or unused imports; keep generated outputs outside Git.
F. Update current doc/map without growing the 305-line system-of-record file;
publish `reports/REFACTOR_ROUND4_STEPS_6_7_2026-09-13.md`. Historical reports
remain snapshots. General changed-code gate and re-prioritization (steps 8–9)
remain queued; mutation is not configured for the touched modules.
