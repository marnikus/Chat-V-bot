# Area B — bridge behavior protection

Parent: [master plan](SAFETY_REFACTOR_2026-09-10_PLAN.md). Status: designed, not implemented.
Goal: improve weak UI/backend boundary protection without redesigning services or Qt routing.

## B1. Understand and constrain scope

Baseline coverage: bridge 67.44% line / 48.43% branch. Particularly weak: StackBridge 92/242 statements and 2/32 branches; CdpBridge 38/74 statements and 0/12 branches; UndoBridge 61/121 statements and 9/26 branches.

Own StackBridge, UndoBridge, CdpBridge and Router only. **DbBridge belongs exclusively to A.** Engine semantics belong exclusively to C. App lifecycle production changes and history push warning cleanup are deferred.

Do not use this task to introduce a shared async scheduler across every bridge. Test existing scheduling boundaries and fix only proved errors in owned modules. A generic scheduler would create unnecessary integration dependencies.

## B2. Test architecture

Create `tests/unit/bridge_safety/` containing `test_stack_commands.py`, `test_stack_presets.py`, `test_undo_wire.py`, `test_cdp_wire.py`, `test_router_contract.py` and local helpers as needed.

- Import real PySide6 QObject/Signal/Slot. Use an ordinary QCoreApplication only if required; no QWidget/WebEngine construction.
- Instantiate actual bridges and EventBus with narrow context/service fakes. Use real stores for a small subset of persistence round trips, not every wire test.
- Observe emitted Qt signals and decode payloads. Assert service call arguments, side effects and absence of forbidden effects.
- Invoke synchronous slots and drain scheduled tasks inside a controlled event loop. Await tasks; never use arbitrary long sleeps, pending-task leaks or unawaited coroutine mocks.
- Validate router delegation through the generated actual Router and Qt metaobject. A fake of the Router itself proves nothing.
- Isolate any app-window stubs using the existing scoped approach. Never modify `tests/conftest.py`, leave fake Qt in `sys.modules`, or change shared stub behavior globally.

## B3. Behavior matrix

| Surface | Cases | What must be proved |
|---|---|---|
| Stack start | Valid list; malformed JSON; wrong JSON shape; already running; enabled/disabled/retired keys | Correct normalized stack passed once, persisted appropriately, exactly one execution scheduled; invalid input has no execution or destructive config change |
| Stop/pause/resume slots | Call each slot | Correct public engine method called once; no assumptions about C's private implementation |
| Engine signal forwarding | step/progress/person/complete signals and missing optional source | Existing signal signatures/payloads preserved; no duplicate relay caused by test setup |
| Stack/template/custom presets | Save/load/delete/list, empty names, duplicates, missing entries, malformed payloads, config errors where handled | Actual round trip and expected notification; failed operations do not emit false success or overwrite valid data |
| Undo input | stack list, invalid JSON/type, valid/invalid grid, unknown kind, service Err | Rejection prevents timeline/config mutation; accepted values use canonical payload |
| Undo/redo output | Ok/Err, empty timeline, stack/grid/other entry, legacy aliases | Correct JSON/null/error log; alias calls global operation once, never creates separate timeline |
| Undo signals/state | HistoryChanged, stack changes | Correct history signal, stored stack/grid update, PeopleChanged only on relevant changes |
| CDP connect | success with true/false value, Err, thrown failure | PeopleChanged only on successful explicit connection; no unhandled task failure or false connected UI |
| Tab discovery/match | Pending return, arguments, results and errors | Slot schedules actual work; event-to-signal payload forwarding preserved |
| Bookmarks | empty/whitespace, add/duplicate, remove missing/existing, remember selection | Correct persistence and payload; detect duplicate notification, but change counts only after deciding current public contract |
| Scheduling | loop available, scheduling unavailable, service raises, cancellation | Coroutines closed/drained; failures observed; no silent success or new warning |
| Router | representative stack/undo/CDP slots, lazy domain creation, context rebinding, invalid Qt names | Delegation hits actual domain object with current context; Qt slot names/arity and bridge signal types stable |

Wrong-shaped JSON behavior is characterized before coding; do not silently broaden accepted wire types. Contract violations found in service implementations are filed to their owner rather than patched here.

## B4. Replace stale registration assertion with behavioral protection

`tests/test_bridge_router.js` currently searches `main.py` for `registerObject("bridge")`. It fails because registration moved to `app/window.py:create_window`.

1. Add `tests/unit/app/test_webchannel_registration_contract.py` that executes real `create_window` with scoped window/channel/view doubles, without starting WebEngine.
2. Assert channel registers the exact provided bridge under `"bridge"`, channel is installed on the page and kept alive on the window, expected local UI URL is loaded, and window is shown.
3. Prove this test fails if registration is removed or the object name changes.
4. Remove only the stale source-location assertion from JS after equivalent behavior is covered. Retain its other wire-contract checks. Do not merely change a regex to another filename and call it behavioral testing.
5. Run all JS entrypoints and existing app/Qt poison-protection tests.

No production change to app/window.py is planned. If the new test reveals a real defect there, obtain explicit ownership before editing.

## B5. Gates and handoff

Run new tests plus `tests/test_bridge_router.py`, `tests/test_history_bridge.py`, existing grid/people undo tests, app harness integrity tests and the full suite.

Target owned Stack/Undo/CDP files ≥85% line / ≥80% branch and bridge aggregate ≥80% / ≥75%. Inspect missing branches from coverage JSON; percentages must not be inflated through import-only assertions, unreachable-code exclusions, fake implementations or blanket mocks. If Router coverage still cannot lift aggregate to target, report which unowned modules require a follow-up rather than expanding silently.

Expected branch independence: tests use frozen public service contracts, not A's new deletion internals or C's new cycle planner. Engine fakes test bridge responsibilities only; full combined suite covers the actual run integration.

Implementation journal (owner fills): branch/head; test inventory and meaningful failure cases; any reproduced boundary bug/fix; coverage before/after; JS 20/20 result; Qt isolation; remaining missing branches.
