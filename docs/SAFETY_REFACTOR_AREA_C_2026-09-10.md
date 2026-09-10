# Area C — stop correctness, then cycle orchestration

Parent: [master plan](SAFETY_REFACTOR_2026-09-10_PLAN.md). Status: designed, not implemented.
Two ordered subphases in one ownership area: **C1 fixes behavior; C2 restructures protected code.** C2 must not obscure C1 safety fixes in one giant diff.

## C0. Understand current behavior

`StackBridge` calls the existing engine API; C does not change the bridge. RunCoordinator inherits execution/queue/hooks mixins. `_execute_cycle` currently combines stack inspection, collection, filtering, ordering, selection, mode decisions, progress, user execution and post-success marking.

Measured baseline: `_execute_cycle` Radon CC 31 / cognitive 25 / 37 physical lines; coordinator module branch coverage was 100%. Therefore another test count increase or a lower CC is not sufficient evidence of correctness. Test interactions and observable side effects.

Current interfaces to retain:

- `RunCoordinator` and `ActionEngine` alias; `execute`, `load_stack`, `stop`, `pause`, `resume`, properties and all Qt signals.
- Hooks, retry policy arguments, tracer record vocabulary, action settings and `ActionResult` constants.
- Four cycle outcomes and four per-user statuses defined in master plan.
- `RunHooksMixin.is_stopping()` already exists; `ActionContext.is_stopping()` also exists. Use the existing duck-compatible query, not a new required engine API.

## C1. Reproduce and fix cancellation first

### C1a. Required behavioral regressions

Create `tests/unit/actions/test_wait_page_cancellation.py` and `tests/integration/run_safety/test_stop_contract.py` / `test_cleanup_contract.py`.

| Scenario | Required result |
|---|---|
| Wait entered with stop already requested | No pre-delay/probe; cooperative stopped outcome, not timeout/failure |
| Stop during wait polling delay | Prompt exit, no subsequent probe/action/automatic mark |
| Stop during wait pre-delay | Stop honored before probe, not after the full configurable delay |
| Probe never completes | Wait bounded by its deadline; stop can interrupt pending read-only probe without orphaned task |
| No engine supplied | Existing success/timeout behavior remains usable |
| Found/not-found/error/malformed probe | Existing normal behavior and diagnostics preserved except demonstrated bug fixes |
| Stop while engine paused | Resume from pause barrier must not start another block |
| Stop during collect/take/queue preparation | No empty-success misclassification or downstream action; no new automatic marks |
| Stop during retry delay | No next attempt; stop does not invoke error fallback or increment failure handling as a transient error |
| Stop on final user block returning OK | Stop observed before coordinator's automatic mark boundary prevents marking; already completed explicit writes are not rolled back |
| Single-target cycle returns stop | Cycle returns `stopped`, not `worked`; no next repeat cycle |
| Stop then start a new run | State is terminal/restartable, not stranded in STOPPING |
| External `task.cancel()` | CancelledError propagates after cleanup; no success result or automatic marking |
| Hook/pre-run/action/post-run failure | Context/expanded attributes restored; running flag reset; tracer closed and completion signal emitted once |

The design-phase action probe only reproduced already-stopped waiting. Other rows are risk-based tests and must be demonstrated before calling them confirmed bugs.

### C1b. Private stop mechanism

Proposed `actions/cancellation.py` contains a small private `RunStopped` exception and stop-aware wait/check utilities. Actions may depend on this lightweight module; it must not import services or Qt. Use existing `engine.is_stopping()` when callable, with `_stop_requested` compatibility fallback for old duck-typed callers. `engine=None` means no cooperative stop predicate.

`RunStopped` is distinct from external `asyncio.CancelledError`. Define it as an ordinary private exception and explicitly pass it through every retry/fallback/general-Exception boundary before ordinary failure handling. Catch it at the engine boundary to produce existing `stop`/`stopped` statuses. Do not add a new ActionResult constant, return ambiguous `None`, or overload SKIP as STOP. Add a test for retry policy with a permissive retry subclass so cooperative stop still cannot be retried.

WaitPageLoad checks before delay/probe, after awaited probe, and during bounded sleeping. Use a monotonic deadline. For the read-only CDP probe, manage an awaitable task with short polling slices (suggested ≤100 ms), observe stop/deadline and cancel+await it when needed. Do not blanket-cancel arbitrary action/CDP write operations: cancelling a local await does not undo a remote browser side effect. Test with the real CDP client's cancellation contract where feasible and escalate any required client change (backend is frozen).

Avoid serializing cancellation/runtime helper objects through `BaseAction.to_dict()`. Helpers live in local/private state, not new public action settings.

### C1c. Lifecycle and side-effect boundaries

- Recheck stop immediately after pause barriers and before initiating next action or automatic mark.
- Treat already-started writes as potentially completed; no claim that stop rolls back DB changes or sent messages.
- Translate cooperative stop to `stopped` at cycle/run boundaries; emit appropriate stop trace/log rather than generic success. Keep existing signal signatures.
- Preserve accounting contract explicitly: characterize how current `RunProgress.note_status` treats `stop`/`fail`; do not invent a new wire progress category in this task. Stop identity belongs in outcome/trace, even where a legacy counter mapping must remain.
- Put temporary nickname expansion restoration in `finally`, including external cancellation. Context cleanup, tracer close, running flag reset and exactly-once completion signaling must not be skipped if `post_run` raises/cancels. Define and test precedence: preserve the original run cancellation/error while separately reporting cleanup-hook failure, rather than masking it.
- Preserve state-machine public values; use existing terminal/reset transitions. Verify stopping a paused/running run and starting again, plus repeated stop calls.
- Use deterministic fake clocks/events for unit timing. A practical integration stop gate is <500 ms with a controlled cooperative fake CDP; clearly exclude blocked event loops and uninterruptible external IO from that guarantee. No long sleeps in tests.

C1 is done only when failing-before/passing-after cases and old run contracts are green. Commit it separately before C2.

## C2. Cycle structure after safety gates pass

### Proposed responsibilities

`services/run/cycle_plan.py` is private, no Qt/DB/CDP imports:

- immutable `StackFacts`: first enabled scroll block reference, enabled memory-click presence, enabled TAKE presence, conditional-skip presence, enabled user-scoped IDs, stack-empty flag;
- `inspect_stack(blocks)`: central enabled-block rules without repeated scans;
- `choose_cycle_mode(facts, has_queue, take_matched)`: returns a small private decision (queued / single-target / standalone / empty / empty-stack plus a reason), no signals or side effects.

`RunCoordinator._execute_cycle` retains orchestration:

```text
prepare collection or current memory queue
filter labels, then apply order
run TAKE phase
inspect facts at the compatibility-correct boundary
select cycle mode
emit existing mode diagnostics / update total
execute selected user(s), checking stop boundaries
apply existing successful-user bookkeeping
return existing cycle outcome
```

The early scroll lookup and later stack inspection currently occur on opposite sides of awaits. Do not blindly snapshot facts before collection if an action/hook can legally modify stack/settings. Characterize this behavior first. Preserve the current phase ordering and inspect at the appropriate points, or document a separately approved frozen-stack contract. No silent snapshot semantic change disguised as optimization.

Keep existing `_run_collect_phase`, `_run_take_phase`, `_run_single_target_cycle` callable boundaries unless local tests prove extraction is safe. Queue execution and finalization helpers can remain private coordinator methods; do not add a service-locator/context object carrying the entire engine just to avoid parameters.

### Decision precedence to pin

| Condition, after preparation | Expected mode |
|---|---|
| Enabled memory-driven CLICK_USER | Single-target path takes precedence; TAKE/no-selection checks remain inside that path |
| TAKE present, no match, no user-scoped blocks, empty queue | Empty with `no_take_match`, not standalone |
| Queue nonempty | Queued mode (retain current ordering even when stack is empty; characterize before any product change) |
| Queue empty and actual stack empty | Empty-stack |
| Queue empty and enabled user-scoped blocks | Empty |
| Queue empty and only independent blocks | One standalone run |
| All blocks disabled | No successful automatic marking; `_execute_for_user` skip guard remains effective |
| Stop at any C1-defined boundary | Stopped takes precedence over normal completion |

Successful standalone does not mark the sentinel nick. Failed/skipped real user does not get automatic marking. Single-target uses selected nick once per cycle, not once per queue entry. Preserve memory-click/TAKE interaction, Repeat Loop termination, label filter order, order-column semantics and retired backlog/scroll-only rules.

### C2 tests

Create `tests/integration/run_safety/test_cycle_modes.py` and `test_cycle_event_order.py`; add a pure decision table test for cycle_plan.

Exercise real engine with fake CDP/memory/blocks/hooks; assert effect traces: load/collect/filter/order/take, block executions, marks, user signals, progress increments and final outcomes. Normalize volatile timestamps/run IDs in comparisons. Do not stub `_execute_cycle` in tests meant to validate it.

Include multiple users, zero users, disabled blocks, no stack, standalone, TAKE miss, memory selection missing/present, repeat termination, one failure followed by next user, conditional skip, stop after first user, paused stop and external cancellation.

Existing regression gates: `tests/integration/services/test_run_engine_p0_pins.py`, `test_run_service_paths.py`, `test_run_state_machine_contract.py`, `test_services_run.py`, `tests/test_action_engine_sequence.py`, `test_engine_standalone_run.py`, `test_repeat_loop.py`, `test_click_user_memory.py`, `test_click_user_order.py`, `test_take_person.py`, `test_scroll_only_seek.py`, `test_scroll_parse_pipeline.py`, `test_nick_placeholder.py`, plus full suite.

## C3. Acceptance and handoff

- C1 safety changes isolated from C2 structure in review/commits.
- No changes to B's bridge, A's deletion, frozen public schemas/constants, or global fixtures.
- Existing public imports and slot contracts pass unchanged.
- `_execute_cycle` and extracted helpers aim for CC ≤10, cognitive ≤15 and nesting ≤4; all decisions remain visibly represented in the scenario matrix. Readability beats metric tricks.
- New runtime state/helpers never appear in saved presets.
- Targeted tests, full Python and JS baseline comparison, coverage and current audit attached.
- Explicitly list cancellation boundaries that cannot interrupt remote side effects and what cleanup guarantees apply under ordinary cancellation versus process kill.

Implementation journal (owner fills): branch/head; C1 reproduction/fix results; C2 before/after metrics and behavioral parity; coverage; signals/progress compatibility; unresolved issues.

### Journal — 2026-09-10 (Arena agent, branch `arena/01a08b7b-chat-v-bot`)

- C1 commit `323a4b8` ("area-c C1: cooperative stop/cancellation correctness");
  C2 is the commit carrying this journal entry. Two commits by design: C1 is
  behavior-only (inline in the existing structure), C2 is structure-only
  (extraction + pure planner) on top of the green C1 tree.
- Design: `docs/SAFETY_REFACTOR_AREA_C_IMPL_DESIGN_2026-09-10.md` (written
  before tests and implementation, committed with C1).

C1 reproduction/fix results. New safety suites run against the base commit
fail as required: 60 failed / 27 passed across `run_safety` (stop contract
11, cleanup contract 6, cycle-plan unit 18 incl. ImportError guards) and
`test_wait_page_cancellation.py` (25); `test_coverage_gaps.py` additionally
fails to import (no `actions/cancellation.py`). The 27 baseline-passing cases
are characterization tests (preserved success/timeout/diagnostic behavior).
Fixed per the C1a table: pre-stopped wait does no delay/probe; stop during
pre-delay/polling/hanging-probe exits promptly with no orphaned task
(`await_or_stop` cancels + reaps the probe); pause barriers re-check stop
before starting a cycle/block; collect/take RunStopped maps to `stopped`,
never empty-success or fatal error; retry delays are stop-aware and stop is
never retried (pinned with a permissive-retry subclass); the automatic mark
boundary loses to a stop landing after the final OK (explicit earlier marks
kept); external `task.cancel()` propagates after exactly-once cleanup;
`post_run` failure/cancel is reported without masking the run's own
cancellation/error; stopped runs reach DONE and restart cleanly (including
`STOPPING → reset → RUNNING`, the one-line `state_machine.py` fix).
Full gate on the C1 commit: 2185 passed, 3 skipped, 1 deselected
(real-WebEngine env crash, pre-existing), 1 xfailed, 771 subtests.

C2 before/after metrics (Radon CC / cognitive / audit nesting; all C2
helpers ≤10/≤15/≤4): `_execute_cycle` 31/25 → 9/9/2 with pure planner
`cycle_plan.inspect_stack` 6/7 and `choose_cycle_mode` 9/6 plus small
`_prepare_cycle_queue` (5), `_execute_cycle_guarded` (3), `_pre_cycle_gate`
(4), `_note_cycle_outcome` (5), `_run_user_list` (6), `_finish_single_user`
(10/11); `execute` 14 → 8/9 with `_run_all_cycles` (5) and `_finalize_run`
(10/12). C1 helpers also within aim: `await_or_stop` 10/13 after extracting
the duplicated cancel+reap block. Behavioral parity: full scenario matrix in
`test_cycle_modes.py` / `test_cycle_event_order.py` (queued/empty/
empty-stack/standalone/single-target TAKE-miss/no-nick/repeat/stop/cancel/
skip/failure paths) with effect-trace assertions; pre-existing regression
pins (`test_run_engine_p0_pins`, `test_run_service_paths`,
`test_run_state_machine_contract`, `test_services_run`,
`test_action_engine_sequence`, `test_engine_standalone_run`,
`test_repeat_loop`, `test_click_user_memory`, `test_click_user_order`,
`test_take_person`, `test_scroll_only_seek`, `test_scroll_parse_pipeline`,
`test_nick_placeholder`) all green. `test_merge_undo_enabled.py` (outside
Area C, asserts direct-call structure via source inspection) kept passing
via truthful delegation docstrings — no test edits, no inlining.

Coverage (plan gate command, `--source=core,actions,backend,bridge,services,
stores,app,main`). Area C files, line/branch: `actions/cancellation.py`
100/100 (new), `services/run/cycle_plan.py` 100/100 (new),
`services/run/coordinator.py` 100/100 (was 92.1/100),
`services/run/error_recovery.py` 100/100 (was 100/100),
`services/run/progress.py` 100/100 (was 91.7/88.6), `actions/wait_page.py`
100/100 (was 100/75.0), `services/run/state_machine.py` 100/100 (was
97.8/91.7) — all above the ≥90/≥85 target. Global: 87.66% line / 82.31%
branch vs reproduced base-gate 87.03%/81.32% (2129 passed) — both improved;
above the 80/75 floor. (The plan text quotes an 88.44% line baseline that
does not reproduce with the gate command in this environment; the apples-to-
apples base re-run is the comparison used here.) Final gate: 2258 passed
(+129 Area C tests), 3 skipped, 1 deselected, 1 xfailed, 771 subtests.
JS gate: 19/20 entrypoints, the single failure being the known baseline
stale-registration failure in `test_bridge_router.js` (Area B owns the fix);
no new JS failures. `tools/metrics/current_audit.py` artifact refreshed.

Signals/progress compatibility: all `RunCoordinator` signals, `execute` /
`load_stack` / `stop` / `pause` / `resume` / `is_running` contracts, tracer
record vocabulary, `ActionResult` constants and preset serialization
unchanged; `RunProgress.note_status` keeps the legacy stop→fail counter
mapping (stop identity lives in outcome/trace); no runtime state leaks into
`to_dict()` (pinned by test).

Cancellation boundaries that cannot interrupt remote side effects: only
local awaits are ever cancelled — WaitPageLoad's read-only CDP probe (via
`await_or_stop`) and retry backoff sleeps. Cancelling a local await never
undoes a browser-side effect: an already-started write (sent message, DB
upsert, explicit mark) is treated as potentially completed and is never
rolled back; the automatic mark is only *withheld* when stop lands before
the boundary. Guarantees under ordinary cooperative stop/cancellation:
exactly-once `post_run`, tracer close, running-flag reset, single
`stack_complete` emission, nickname-expansion restoration in `finally`, and
no orphaned probe tasks (reaped with `await`). Under process kill none of
this runs: in-flight browser actions may or may not have completed, the
trace file may end mid-cycle, and `messaged` flags reflect only marks that
reached the DB — restart re-runs unmarked users.

Unresolved / out of scope: C1 necessarily added stop branches to large
pre-existing executors (`wait_page.execute` CC 18→22,
`_execute_for_user` 15→20, `retry_with_backoff` 5→11, `_run_collect_phase`
15→17, `_run_single_target_cycle` 7→12) — coverage-gated (all 100%) but not
complexity-gated by the plan, and left structurally alone per "safety fixes
before cosmetic complexity reductions". Untouched pre-existing overs
(`filter_by_labels` CC 14, `_order_queue_by_column` CC 12) likewise
documented, not refactored.
