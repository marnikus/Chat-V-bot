# History push lifecycle safety — split plan (H1/H2/H3)

Date: 2026-09-10. Status: planned, not implemented.
Design: `docs/archive/2026-09-10-history-push-and-sort/HISTORY_PUSH_LIFECYCLE_DESIGN_2026-09-10.md` (read first;
it defines the contracts each area relies on).

Goal: three areas that can be implemented on **separate branches in
parallel** and merged in any order. Independence is by file/method
ownership (table below) plus contract-first interfaces — no area
imports or assumes another area's new code.

## Ownership table (normative — do not edit outside your column)

| File / region | H1 subscription | H2 in-flight | H3 shutdown |
|---|---|---|---|
| `services/history/runtime.py` `PushBindings` | owns | — | — |
| `services/history/runtime.py` `CollectorRuntime`/`WorldSwitcher` | — | owns | — |
| `services/history/export.py` `init`/`close`/push wiring | owns | — | — |
| `services/history/__init__.py` attrs | owns | — | — |
| `services/collector_service.py` `handle_push`/drain | — | owns | — |
| `app/lifecycle.py` | — | — | owns |
| `tests/integration/history_push/test_subscription_lifecycle.py` | owns | — | — |
| `tests/integration/history_push/test_push_isolation.py` | — | owns | — |
| `tests/integration/history_push/test_shutdown.py` | — | — | owns |
| Everything else (incl. `backend/cdp_client.py`, `services/db_lifecycle.py`, `stores/*`, `bridge/*`) | frozen | frozen | frozen |

`tests/integration/history_push/__init__.py`: whoever lands first
creates the empty file; the others rebase around a one-line add.

## Contracts between areas (from the design doc)

- H1 → all: after `close()` returns, zero history listeners remain on
  the CDP client and no Qt reconnect handler survives. `_on_binding`
  semantics unchanged.
- H2 → all: when `stop()`/`detach_db()`/`switch_db()`/`close()`
  return, zero push tasks are in flight and `_push_open` reflects
  readiness. `close()` needs no edit: drain rides inside the existing
  `_stop_collector()` call.
- H1+H2 → H3: `close()` is idempotent, unsubscribes, drains, flushes,
  closes. H3 builds against this contract (fakes allowed) and never
  reaches into push internals.

## H1 — Push subscription lifecycle (P1, the confirmed bug)

Branch: `arena/h1-push-subscription` (suggested). Base: `main` (+A/C
as available; no dependency on H2/H3).

1. `PushBindings`: split install into browser-binding ensure +
   once-only subscription ensure; `rebind()` reinstalls the browser
   binding only; add idempotent `uninstall()` via `off_event`.
2. `init()` idempotent (named `_on_connected` slot, connect-once
   guards); `close()` unsubscribes + Qt-disconnects first.
3. Tests (fail-before/pass-after): install + N rebinds → exactly 1
   listener; one push event → exactly 1 `handle_push` after reconnects;
   close removes listener + Qt handlers; init→close→init clean;
   double close safe; duck-typed CDP without `on_event`/`off_event`
   still works.
4. Acceptance: new tests green; full Python suite green; JS gate
   unchanged; owned-region coverage ≥90% line / ≥85% branch.

## H2 — In-flight push isolation (P1 investigation + fix)

Branch: `arena/h2-push-isolation` (suggested). Base: same as H1; no
dependency on H1/H3 (works with or without them; combined merge is
verified by integration).

1. `Collector`: `_inflight` set + `_push_open` gate + `_world_gen`
   (all state on the Collector — `HistoryService.__init__` untouched);
   register/discard in `handle_push` via `asyncio.current_task()`;
   gate closed → silent `return 0`.
2. `Collector.drain_pushes(timeout)`: close gate, bounded wait, cancel
   leftovers, log counts. Called first in `CollectorRuntime.stop()`;
   gate re-opened in `restart()`/`start()` on actual restart.
3. Tests (fail-before/pass-after): mid-`append` push across
   `switch_db` writes nothing into the new world; push across
   `detach_db`/`close` never touches a closed DB and `close()` returns
   with zero in flight; stuck push is cancelled after timeout and the
   switch proceeds; stop-then-no-restart silences pushes; restart
   re-enables them.
4. Acceptance: the wrong-world failing-before test demonstrated;
   new tests green; full suite green; owned-region coverage targets as H1.

## H3 — Shutdown path hardening (P2)

Branch: `arena/h3-shutdown-order` (suggested). Base: same as H1/H2;
builds against the documented `close()` contract.

1. `app/lifecycle.py` only: persist-first order (engine stop →
   history.close → memory.close → bounded straggler-cancel →
   cdp.disconnect → quit); per-stage `wait_for` timeouts with named
   stuck-stage logs; quit never hangs.
2. Tests with fakes + a real ordered integration test: stage order
   asserted; hung history close → timeout + proceed + quit; close
   raising → warning + proceed; double shutdown → single run.
3. Acceptance: new tests green; full suite green; shutdown paths
   covered (previously weak — report before/after numbers).

## Merge / integration

- Any merge order works; suggested H1 → H2 → H3 (defect first).
- After each merge: run all three areas' tests together plus the
  complete suite and the JS gate. Never resolve a conflict by deleting
  coverage or weakening an assertion.
- Integration check (whoever merges last): combined run of
  `tests/integration/history_push/` + full suite + JS gate, and a
  combined reconnect-during-switch stress test (reconnect storm while
  switching worlds: exactly-once subscription, zero cross-world
  writes) — owned by the integrator, not by any single area.

## Explicitly deferred

- `media_fetch.py` attach/detach audit (same bug class, already paired
  correctly at a glance — needs its own reproduction, not assumed).
- Write-side world token inside `repo.append` (rejected: touches
  frozen store code; drain + gates suffice).
- P3 complexity refactors (`_item`, `score_tab`, large classes).

---

# Detailed implementation plans (no code in this doc change)

Each area below is written so a separate branch session can implement
it without re-deriving anything: exact method-level changes, new
attributes, test cases with assertions, and the gate that finishes the
area. Follow test-first within each area: new tests land and are shown
failing-before (or ImportError-free failing) before the fix.

Conventions: "owned region" = the only production code the area may
edit (see ownership table). All areas keep public names/signatures:
`HistoryService`, `init/close/start/switch_db/detach_db`,
`_install_push_binding/_rebind/_on_disconnected/_on_binding`,
`_stop_collector/_restart_collector`, `Collector.handle_push/run/
start/stop`, `ApplicationLifecycle.startup/shutdown/bind`.

## H1 detailed plan — Push subscription lifecycle

### H1.1 Production changes

**`services/history/__init__.py` — `HistoryService.__init__`:**
add two attrs next to `self._binding = False` (H1 owns this region):

- `self._subscribed = False` — "Python `on_event` subscription is
  registered on the current `self.cdp` object".
- `self._signals_connected = False` — "Qt `connected/disconnected`
  handlers are attached".

**`services/history/runtime.py` — `PushBindings`** (rewrite of
`install`, `rebind`; new `uninstall`; `on_disconnected`/
`on_binding` untouched):

- `async def install()` becomes the first-time orchestrator:
  `await self.ensure_browser_binding()` then
  `self.ensure_subscription()` (sync; `on_event` is sync).
- `async def ensure_browser_binding()`: current `install()` body
  minus the `on_event` lines; guarded by `host._binding`; keeps the
  `hasattr(add_binding)` duck-type check and the try/except returning
  early on failure. Sets `host._binding = True` only when
  `add_binding` returns truthy.
- `def ensure_subscription()`: if `host._subscribed` → return; if
  `hasattr(host.cdp, "on_event")` → `host.cdp.on_event(
  "Runtime.bindingCalled", host._on_binding)`; set
  `host._subscribed = True` only after the call succeeds (if
  `on_event` raises, let it propagate — a broken fan-out must be
  loud, matching `media_fetch.attach`).
- `async def rebind()`: `host._binding = False`, then `await
  self.ensure_browser_binding()` — and nothing else.
- `async def uninstall()` (new, idempotent): if not
  `host._subscribed` → still clear `host._binding = False` and
  return; else if `hasattr(host.cdp, "off_event")` → `host.cdp.
  off_event("Runtime.bindingCalled", host._on_binding)` inside
  try/except `Exception → log.debug` (a half-torn-down fake client
  must not break `close()`); finally clear both flags. Async only so
  `close()` can `await` future async teardown uniformly; today it
  awaits nothing.
- `on_disconnected()` unchanged (`_binding = False` only — the
  subscription survives a transport drop; the binding is reinstalled
  on `connected`).

**`services/history/export.py`:**

- New named slot (module-private method on the mixin):
  `def _on_connected(self): asyncio.ensure_future(self._rebind())`
  (import asyncio already present).
- `init()`: replace the anonymous `connected` lambda with
  `connected.connect(self._on_connected)`; wrap BOTH Qt connects in
  `if not self._signals_connected: ...; self._signals_connected =
  True` (keep the existing `hasattr(connect)` duck-type guards).
  Rest of `init()` unchanged, including `_install_push_binding()`
  call position.
- `close()`: new first block before `_stop_collector()`:
  `await self._push.uninstall()`, then best-effort Qt disconnects:
  `for sig in (connected, disconnected)` guarded by `hasattr(sig,
  "disconnect")`, each in try/except `Exception → log.debug`
  (disconnecting a never-connected Qt signal raises `RuntimeError`;
  fakes may lack it). Then existing body verbatim. Rationale for
  first position: no *new* events accepted before H2's drain (inside
  `_stop_collector`) and the flush/close that follow.

### H1.2 Edge cases to pin

- CDP without `on_event`/`off_event` (old duck-typed fakes):
  install/uninstall degrade to binding-only, no crash.
- `add_binding` returning falsy / raising: `_binding` stays False,
  no subscription attempted (current behavior preserved).
- `close()` twice, `init()` after `close()`, `init()` twice without
  close: listener count stays ≤1, Qt handlers attached once.
- `rebind()` while never installed: installs browser binding, adds
  the single subscription (covers the `_binding=False` + fresh-cdp
  path some tests construct manually).

### H1.3 Tests — `tests/integration/history_push/
test_subscription_lifecycle.py` (new file; fake CDP counting
`on_event`/`off_event` calls + real `HistoryService` with tmp DB;
Qt signals via PySide6 offscreen like existing service tests)

1. `install_plus_two_rebinds_registers_once` — the user's
   reproduction, asserted as `== 1`.
2. `one_push_event_calls_handle_push_once_after_reconnects` —
   dispatch a synthetic `Runtime.bindingCalled` frame through the
   fake's listener list; count handler invocations.
3. `close_removes_listener_and_qt_handlers` — counts after close are
   zero; a post-close dispatched event invokes nothing.
4. `init_close_init_is_clean` — reopen leaves exactly 1 listener,
   1 connected-handler; no duplicates.
5. `double_close_is_safe` and `init_twice_without_close_is_safe`.
6. `duck_typed_cdp_without_events_still_inits_and_closes`.
7. `rebind_without_prior_install_subscribes_once`.
8. `uninstall_is_idempotent_and_clears_flags`.

### H1.4 Gate

New tests fail before (run them against the base: ≥1 assertion fails —
the count tests), pass after; `tests/integration/history_push/` green;
full Python suite green; JS gate unchanged (no JS touched);
`PushBindings` + touched `export.py` regions ≥90% line / ≥85% branch
(measure with the plan gate coverage command, `--include` the two
files); `git diff --check` clean.

## H2 detailed plan — In-flight push isolation

### H2.1 Production changes (all state on `Collector`)

**`services/collector_service.py` — `Collector.__init__`:** add

- `self._inflight: set = set()` — currently executing
  `handle_push` tasks.
- `self._push_open: bool = True` — admission gate for new pushes.
- `self._world_gen: int = 0` — bumped on every world-pointer move;
  used in debug logs and assertions (not a write-side check).

**`Collector.handle_push`:** new first lines (before the existing
`_nick`/`enabled`/`_paused` checks):

- `if not self._push_open: return 0` (silent — closed is a normal
  lifecycle state, not an error).
- `task = asyncio.current_task()`; `if task is not None:
  self._inflight.add(task)`; wrap the entire existing body in
  `try: ... finally: self._inflight.discard(task)`.
  No other semantic change: same gates, same append, same
  never-raises contract (note: `except Exception` must keep NOT
  catching `CancelledError` — verify by reading, add a test).

**`Collector.drain_pushes(timeout: float = 2.0) -> dict`** (new):

- Set `self._push_open = False`.
- Snapshot `pending = [t for t in self._inflight if not t.done()]`.
- If pending: `done, still = await asyncio.wait(pending,
  timeout=timeout)`; for `t in still`: `t.cancel()`; then
  `await asyncio.gather(*still, return_exceptions=True)`.
- `return {"drained": len(done), "cancelled": len(still),
  "world_gen": self._world_gen}`; `log.info` the counts at debug
  level when nonzero (info when cancelled > 0).
- Must never raise: wrap the whole body so a drain failure degrades
  to best-effort + warning (a stuck drain must not wedge
  `switch_db`/`close`).

**`services/history/runtime.py`:**

- `CollectorRuntime.stop()`: new first line `await host.collector.
  drain_pushes()` (uses default timeout; the method stays async).
  Rest unchanged. This single call-site covers `detach_db`,
  `switch_db` (both park via `_stop_collector`) and `close()`.
- `CollectorRuntime.restart(state)`: after the existing
  start-or-collector-start logic, set `host.collector._push_open =
  True` whenever a restart actually happened (either branch).
  H2 may add a tiny `Collector.reopen_pushes()` setter instead of
  touching the attr cross-class — preferred for readability.
- `CollectorRuntime.start()`: after ensuring the task/collector,
  call the same reopen (covers direct start-after-stop flows).
- `WorldSwitcher._rebind_db()`: after rebinding, `host.collector.
  _world_gen += 1` (or a `note_world_moved()` helper on Collector).
  No behavior change — observability + test hook.
- No changes to `switch_db`/`detach_db` bodies, `close()`,
  `PushBindings`, or `HistoryService.__init__`.

### H2.2 Ordering proof (why no window remains)

- Switch path: `switch_db` → `_stop_collector` → `drain_pushes`
  (gate closed, in-flight awaited/cancelled) → old DB closed →
  `_rebind_db` (gen bump) → `reset_state` (nick/verified cleared) →
  restart (gate re-opened). Any push that registered is drained; any
  push dispatched-but-unscheduled starts after `reset_state` and
  returns 0 at the `_nick`/`_verified` gate; `_push_open` adds a
  second independent gate.
- Detach/close path: same drain, then close; late starters hit
  closed `_push_open` (silent 0) or, belt-and-braces, the existing
  closed-DB containment in `handle_push`.
- Shutdown path: unchanged blanket-cancel still exists until H3;
  H2 additionally guarantees `close()`-level determinism when
  shutdown (post-H3) calls `close()` before cancelling stragglers.

### H2.3 Tests — `tests/integration/history_push/
test_push_isolation.py` (real `HistoryService` + tmp worlds; a
barrier-controlled repo wrapper to pause mid-`append`; event-driven,
no long sleeps)

1. `push_mid_append_across_switch_writes_nothing_to_new_world`
   (THE failing-before test): start push in world A, pause inside
   append, `switch_db(B)`, release; assert B contains zero rows from
   the push and A contains exactly the pre-switch rows; assert the
   push task completed (drained, not orphaned).
2. `push_across_detach_never_touches_closed_db`: pause mid-append,
   `detach_db()`, release; assert clean return 0, no exception, no
   write after close.
3. `stuck_push_is_cancelled_and_switch_proceeds`: never-release the
   barrier; `switch_db` returns within timeout+slack; drain report
   shows cancelled=1.
4. `stop_without_restart_silences_pushes_until_start`: after
   `_stop_collector()`, dispatch → 0 and no task registered; after
   `start()`, pushes flow again.
5. `restart_reopens_pushes_after_switch`: post-switch push in the
   new world appends normally (guards against a stuck-closed gate).
6. `cancelled_push_propagates_cancelled_not_exception`: direct
   `handle_push` task cancelled mid-append → `CancelledError`
   surfaces to the awaiting test (documents the never-swallow rule).
7. `drain_report_counts_and_never_raises`: unit-level drain with
   0/1/many in-flight incl. an already-done task.
8. `world_gen_bumps_on_every_rebind`: switch twice → gen advanced
   twice (observability hook for the integrator test).

### H2.4 Gate

Test 1 demonstrated failing-before ( cross-world write observed on
base); all new tests pass after; history/collector/world suites +
full Python suite green; JS unchanged; owned regions
(`handle_push`, `drain_pushes`, `stop/restart/start` deltas,
`_rebind_db` delta) ≥90/85; diff-check clean.

## H3 detailed plan — Shutdown path hardening

### H3.1 Production changes (`app/lifecycle.py` only)

Rewrite `shutdown()` as explicit stages (keep `_shutdown_started`
guard, keep `bind()`/`startup()`/`start()` untouched):

1. `engine.stop()` (sync, guarded try/except → warning).
2. Undo pendings: keep existing gather but wrap in
   `asyncio.wait_for(..., timeout=2.0)`; `TimeoutError` → warning
   naming the stage.
3. `await asyncio.wait_for(self.history.close(), timeout=10.0)` —
   history FIRST while CDP is still up (drains + flushes + closes).
4. `await asyncio.wait_for(self.memory.close(), timeout=10.0)`.
5. Straggler cancel (moved AFTER graceful closes): all-tasks-minus-
   self cancel + `gather(return_exceptions=True)` inside
   `wait_for(timeout=5.0)`; log how many were reaped.
6. `await asyncio.wait_for(self.cdp.disconnect(), timeout=5.0)`.
7. `finally: log.info("Shutdown complete"); self.app.quit()`.
   Every stage logs start/finish at debug and failures/timeouts at
   warning with the stage name. No stage may raise out of
   `shutdown()` except `CancelledError` of shutdown itself (re-raise
   after `app.quit()` attempt? No — keep current swallow-and-quit;
   document the choice).

Timeout values are module constants (`_UNDO_TIMEOUT = 2.0`,
`_CLOSE_TIMEOUT = 10.0`, `_REAP_TIMEOUT = 5.0`,
`_DISCONNECT_TIMEOUT = 5.0`) so tests can monkeypatch small values.

### H3.2 Tests — `tests/integration/history_push/test_shutdown.py`
(fakes for engine/history/memory/cdp/bridge recording call order;
one real ordered integration test with tmp services)

1. `shutdown_order_is_persist_first`: assert call sequence
   engine.stop → history.close → memory.close → (straggler cancel) →
   cdp.disconnect → app.quit.
2. `hung_history_close_times_out_and_quit_still_runs`: history.close
   gated forever (small monkeypatched timeout); quit called; warning
   names the stage.
3. `raising_close_proceeds_with_warning`: history.close raises;
   memory.close + disconnect + quit still run.
4. `double_shutdown_runs_once`: second call returns immediately,
   no duplicate closes.
5. `straggler_task_is_reaped_after_close`: background task alive
   past closes gets cancelled and shutdown completes.
6. `undo_pendings_waited_with_timeout`: slow pendings → timeout path,
   shutdown proceeds.

### H3.3 Gate

New tests pass (they fail before only where the old order differs —
tests 1–2 are the behavioral delta; document per-test before/after);
full suite green; JS unchanged; `app/lifecycle.py` coverage reported
before/after (must improve; target ≥90/85 on the rewritten method);
diff-check clean.

## Integration (whoever merges last)

1. Merge order suggested H1 → H2 → H3; any order acceptable. After
   each merge: all `tests/integration/history_push/` tests + full
   Python suite + JS gate.
2. Combined stress test (integrator-owned, may live in any area file
   or a new `test_push_storm.py`): reconnect storm (10 rapid
   connect/disconnect cycles) concurrent with a world switch and a
   burst of pushes → assert exactly 1 listener, ≥1 drained or
   completed push each accounted once, zero rows in the wrong world,
   zero in-flight at end, clean close.
3. Final artifacts: per-area coverage for owned regions, global
   before/after line+branch vs the gate baseline, JS gate result,
   `current_audit.py` output. Coverage/JS commands are the repo's
   standard gate (see SAFETY plan §commands); do not invent new ones.
4. Conflict rule (same as the Area plan): never resolve by deleting
   coverage or weakening an assertion. Expected conflicts: none
   (disjoint regions) except the one-line `history_push/
   __init__.py` creation race.
