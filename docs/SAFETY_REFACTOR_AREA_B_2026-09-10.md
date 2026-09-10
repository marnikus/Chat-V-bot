# Area B — bridge behavior protection

Parent: [master plan](SAFETY_REFACTOR_2026-09-10_PLAN.md). Status: implemented (tests + three boundary fixes).
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

---

# Implementation journal (owner: this session)

## Context

- Branch: `arena/01a08b7b-chat-v-bot`
- Head at start: `3820136a74df98a852bf0b3a1f227f0c73e0208b` (plan baseline commit)
- Scope: Area B only. Production edits limited to `bridge/stack_bridge.py` and `bridge/cdp_bridge.py` (both B-owned). No frozen files touched. No DbBridge, engine, `app/window.py`, `tests/conftest.py` or shared-stub changes.

## Implementation design (structure) — written before code

### New test structure

```
tests/unit/bridge_safety/
    helpers.py                 # FakeEngine(QObject), FakeCdpService, LogCapture, drain()
    test_stack_commands.py     # run/stop/pause/resume, signal forwarding, _schedule
    test_stack_presets.py      # stack/template/custom-block presets
    test_undo_wire.py          # global undo timeline wire contract + aliases
    test_cdp_wire.py           # connect/tabs/match/bookmarks + scheduling
    test_router_contract.py    # real Router delegation, lazy creation, context rebinding
tests/unit/app/test_webchannel_registration_contract.py   # B4 (real create_window under scoped stubs)
```

Design rules applied: real PySide6 QObject/Signal/Slot everywhere; real EventBus; real ConfigManager/PresetStore for persistence round trips; real UndoService for the undo wire; narrow service fakes only at the CDP boundary; scheduled coroutines drained inside `asyncio.run` (no sleeps, no leaked tasks, no unawaited mocks); Router validated through the generated real `Router` + Qt metaobject; app-window stubs reused from `tests/unit/app/qt_stubs.py` (scoped, restored).

### Reproduced defects (characterized before coding)

1. **StackBridge.run_stack accepts wrong JSON shape and executes it.** Real probe:
   - `run_stack('"just a string"')` → `engine.load_stack([])` + `engine.execute()` scheduled (silent empty-stack run).
   - `run_stack('{}')` → same.
   - `run_stack('42')` → `normalize_blocks(42)` raises `TypeError: 'int' object is not iterable` inside the slot (uncaught).
   Contract says invalid input must have **no execution and no destructive config change**. `save_stack_preset`/`snapshot_stack` already reject non-lists; `run_stack` is the odd one out.
2. **CdpBridge._do_connect leaves an unhandled task failure when the service raises.** Real probe: fake `cdp_service.connect()` raising `RuntimeError` → `Task exception was never retrieved` warning, and no `LogMessage` is emitted (silent failure). Contract: no unhandled task failure; failures observed.

### Fix plan (minimal, test-proved)

1. `StackBridge.run_stack`: after `json.loads`, reject anything that is not a list with an error log and return — before `engine.load_stack`, `config.set_state`, or scheduling `execute`.
2. `CdpBridge._do_connect`: wrap `await cdp_service.connect(...)` in try/except; on exception emit a `LogMessage(level="error")` and return, so no task failure goes unobserved and no false `PeopleChanged` is emitted.

Everything else in the B3 matrix is characterized (and pinned) by tests without production change.

### B4 plan

Add `tests/unit/app/test_webchannel_registration_contract.py` (real `create_window`, scoped stubs). Then delete only the stale `main.py` source grep in `tests/test_bridge_router.js`, keeping its other wire-contract checks. Sensitivity is demonstrated by temporarily removing `channel.registerObject("bridge", bridge)` and confirming the new test fails (see results).

## Results (filled after implementation)

### Commands that gate Area B

```bash
# new Area B tests + B4 registration contract
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m pytest \
  tests/unit/bridge_safety/ tests/unit/app/test_webchannel_registration_contract.py -q
# → 118 passed

# targeted wire-parity / history / grid+people undo gates
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m pytest \
  tests/test_bridge_router.py tests/test_history_bridge.py tests/test_merge_undo_enabled.py \
  tests/test_people_undo.py tests/test_person_labels.py tests/test_archive_delete_undo.py -q
# → 129 passed

# full suite (real-WebEngine grid test deselected as in the plan baseline)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
# → 2247 passed, 3 skipped, 1 deselected, 1 xfailed, 771 subtests passed, 1 warning

# JS entrypoints
for f in tests/test_*.js; do node "$f"; done
# → 20/20 pass (the single stale main.py-registerObject assertion was replaced by B4)
```

### Test inventory and meaningful failure cases

Seven new files: `tests/unit/bridge_safety/{helpers.py, test_stack_commands.py,
test_stack_presets.py, test_undo_wire.py, test_cdp_wire.py, test_router_contract.py}`
and `tests/unit/app/test_webchannel_registration_contract.py`.

The new tests first failed against the baseline in ways that pin real boundary
behavior (all now green after the fixes below, without weakening any assertion):

- `run_stack` wrong-shape JSON (`"just a string"`, `{}`, `42`) executed / config-wrote
  or raised an uncaught TypeError before the fix — now `"❌ Stack is not a list of blocks"`
  with no execution and no config write.
- `CdpBridge` connect: a raising `cdp_service.connect` became an unretrieved task with
  no `LogMessage` and no false `PeopleChanged` — now logged and returned.
- `save_custom_block`/`delete_custom_block` called nonexistent `BlockStore.save_block` /
  `.delete` — now `save_custom_block` (with a `Result.is_err` error log) / `delete_custom_block`.

### Reproduced boundary bugs fixed (production, B-owned only)

1. `bridge/stack_bridge.py::run_stack` now rejects every non-list `json.loads` result
   before `engine.load_stack`, `config.set_state`, or scheduling `execute`.
2. `bridge/stack_bridge.py::save_custom_block` / `delete_custom_block` now call the real
   `BlockStore.save_custom_block` / `delete_custom_block`.
3. `bridge/cdp_bridge.py::_do_connect` now wraps `await cdp_service.connect(...)` in
   try/except, emits an error `LogMessage`, and returns (no unhandled task, no false
   `PeopleChanged`).

No frozen files, DbBridge, engine, `app/window.py`, `tests/conftest.py`, stores, services,
or shared-stub files were modified.

### Coverage before → after (coverage.py, branch enabled)

| Scope | Before | After | Gate |
|---|---|---|---|
| StackBridge | 92/242 stmts, 2/32 br | **100.0% line / 100.0% branch** | ≥85 / ≥80 ✓ |
| UndoBridge | 61/121 stmts, 9/26 br | **100.0% line / 94.2% branch** | ≥85 / ≥80 ✓ |
| CdpBridge | 38/74 stmts, 0/12 br | **100.0% line / 100.0% branch** | ≥85 / ≥80 ✓ |
| Router (owned) | — | **100.0% line / 92.5% branch** | aggregate only |
| bridge aggregate | 67.44% line / 48.43% br | **85.56% line / 64.53% branch** | ≥80 line ✓ / ≥75 br ✗ |

### Qt isolation / warnings

`tests/unit/app/test_harness_no_qt_poison.py` and the `tests/conftest.py` Qt-isolation
gates stay green (included in the 2243-passed full run). The new `bridge_safety` +
registration-contract suite runs clean with `-W error::RuntimeWarning`. The single
remaining full-suite warning is pre-existing and outside Area B: `tests/integration/
services/test_services_history.py::TestLifecycle::test_push_binding_ignores_other_bindings`
(a `Collector.handle_push` coroutine never awaited in the excluded `services/history/*`
area). Area B adds no new unawaited tasks.

### Remaining missing branches — aggregate shortfall and follow-up request

Owned files are at or above their per-file gates, but the **bridge aggregate branch**
is 64.53% against the 75% target (gap ≈ 33 branch-equivalents of 320). Even 100% branch
coverage of the four owned files cannot close this: the shortfall lives almost entirely
in modules B does not own. Missing-branch inventory (full-suite run):

| Module | Branches | Missing | Partial | Branch-equiv missed | Owner |
|---|---|---|---|---|---|
| bridge/history_bridge.py | 90 | 53 | 25 | 65.5 | services/history area (excluded from B) |
| bridge/collector_bridge.py | 30 | 13 | 13 | 19.5 | collector/archive area |
| bridge/label_bridge.py | 16 | 6 | 4 | 8.0 | other area |
| bridge/layout_bridge.py | 12 | 8 | 0 | 8.0 | other area |
| bridge/people_bridge.py | 8 | 3 | 1 | 3.5 | other area |
| bridge/db_bridge.py | 10 | 2 | 2 | 3.0 | **Area A** (exclusive) |
| bridge/router.py (owned) | 60 | 3 | 3 | 4.5 | B — 3 defensive branches only |
| bridge/undo_bridge.py (owned) | 26 | 1 | 1 | 1.5 | B — 1 unreachable elif-false |

Remaining owned-file gaps are defensive/environmental, not behavior: `router._meta_members`'s
"neither Signal nor Slot" metaobject-method probe edge, `router._bridge`'s spec-vs-router
drift guard (a spec name missing from the built router), `router._ctx_property(setter_sync=False)`
(a parameter no call site uses), and `undo_bridge.push_global_history`'s
`elif kind == "stack"` false edge (unreachable: the earlier `else: return False` already
guarantees `kind` is "stack" or "grid" at that point). Closing them would require fake
QMetaObject manipulation or invoking dead code, which the plan forbids.

**Requested follow-up (integration owner):** assign the `history_bridge`, `collector_bridge`,
`label_bridge`, `layout_bridge`, and `people_bridge` branch work to their owning areas
(`db_bridge` is already A's), or explicitly relax the aggregate-branch target for B to the
owned-file aggregate (100.0% line / 95.5% branch). Area B will not expand into unowned
modules to inflate the aggregate.

### Handoff summary

- Changed files: `bridge/stack_bridge.py`, `bridge/cdp_bridge.py` (production, B-owned);
  `tests/test_bridge_router.js` (stale `main.py` assertion removed only after B4 proved the
  behavior); the 7 new test files; this journal.
- Public contract changes: none beyond the three proved boundary fixes; router slot/signal
  names and arities are unchanged (asserted through the real Qt metaobject).
- `app/window.py` has no diff; the B4 contract test fails if `channel.registerObject("bridge", bridge)`
  is renamed or removed (mutation-checked).
