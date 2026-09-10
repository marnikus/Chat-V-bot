# History push lifecycle safety — design

Date: 2026-09-10. Status: designed, not implemented.
Parent idea: "make the next small work area History push lifecycle safety —
reconnect, unsubscribe, in-flight tasks, and world-switch isolation".

Scope is strictly the history push channel and its shutdown/switch
boundaries. Frozen / out of scope: `backend/cdp_client.py` semantics
(`on_event`/`off_event`/`_dispatch_event` as-is), `services/db_lifecycle.py`
(Area A owns the switch/delete orchestration), bridges, `media_fetch.py`
(same bug class, separate follow-up), `_item`/`score_tab`/large-class
 refactors (P3, no defect reproduced).

## 1. Problem analysis (verified against code)

### 1.1 Confirmed: rebind registers a duplicate listener every time

Chain (`services/history/export.py` → `services/history/runtime.py` →
`backend/cdp_client.py`):

- `HistoryExportService.init()` connects `cdp.connected → self._rebind()`
  and calls `_install_push_binding()`.
- `PushBindings.rebind()` sets `host._binding = False` and calls
  `install()`.
- `install()` calls `host.cdp.on_event("Runtime.bindingCalled",
  host._on_binding)` on **every** pass.
- `CDPClient.on_event` appends unconditionally; nothing ever calls
  `off_event` for history (`grep` proves the only `off_event` caller is
  `stores/media_fetch.py`, which correctly pairs attach/detach).

Result: initial install + N reconnects = N+1 identical listeners; one
incoming `Runtime.bindingCalled` runs `collector.handle_push` N+1 times
concurrently (duplicate DB work, duplicate notifications; callbacks
survive `close()`). Reproduced in isolation: install + two rebinds → 3
listeners, expected 1. Duplicate stored messages / corruption are NOT
yet demonstrated — only the duplicate registration.

Secondary instance of the same defect: `init()` connects Qt signals
with an anonymous lambda (`connected.connect(lambda: ...)`) on every
call, so a close/reopen cycle (`close()` disconnects nothing) stacks
duplicate `connected` handlers too, each firing `_rebind()`.

### 1.2 In-flight pushes are untracked fire-and-forget tasks

`CDPClient._dispatch_event` wraps the awaitable returned by
`_on_binding` → `collector.handle_push` in `asyncio.create_task` and
drops the handle. Consequences:

- `CollectorRuntime.stop()` cancels only the heartbeat `host._task`;
  in-flight `handle_push` tasks keep running across `stop()`,
  `switch_db()`, `detach_db()` and `close()`.
- `WorldSwitcher._rebind_db` swaps `host.repo.db` (plus query/media)
  while a push may be awaiting inside `repo.append` — and the repo
  parts deliberately read `db` **at call time** off the repo object
  (`stores/history_repo.py`). A push admitted in world A can therefore
  commit into world B. `collector.reset_state()` on switch only gates
  *new* pushes (`_nick`/`_verified` cleared); it cannot recall one
  already past the gate. Mechanism confirmed; a failing-before test is
  the H2 investigation deliverable.
- After `detach_db()`/`close()` the DB is closed; a late push raises
  `RuntimeError("history database is not open")` inside `append`, which
  `handle_push` contains (`return 0` + warning). Fail-safe but noisy
  and untested; partial multi-statement appends across a close are
  possible in theory (aiosqlite serialises per connection; close
  commits first).
- `Collector.stop()` sets `_running = False`, but `handle_push` gates
  only on `_nick`/`enabled`/`_paused`/`_verified` — never on
  `_running`. Stopping the collector does not stop push processing.

### 1.3 Shutdown ordering and bounds (`app/lifecycle.py`)

- `shutdown()` blanket-cancels **all** tasks *before* any close, then
  `cdp.disconnect()`, then `history.close()`, then `memory.close()`.
  In-flight pushes are cancelled rather than drained (data-loss
  accepted silently at every quit, non-deterministically).
- `disconnect()` precedes `history.close()`; anything in close/flush
  that still needs CDP (today: nothing directly; post-H2 drain: media
  recovery inside a drained push) races a torn-down client.
- `history.close()` / `memory.close()` are unbounded — a hung close
  hangs `app.quit()` with no log line saying which stage stuck.
- `bind()` fires shutdown fire-and-forget off `window.closing`; the
  `_shutdown_started` flag is the only re-entrancy guard. Adequate,
  keep.

## 2. Design

Separate three lifetimes that are currently tangled:

1. **Browser binding** (`Runtime.addBinding __cvbPush`): reinstall when
   Chrome reconnects. Cheap, idempotent server-side.
2. **Python event subscription** (`on_event`): register once per
   service instance; remove on close. Never re-added by reconnect.
3. **In-flight push work**: tracked tasks bound to the world generation
   that admitted them; drained (bounded) before any DB close/rebind;
   new pushes gated while draining/detached/closed.

### 2.1 H1 — Push subscription lifecycle (the confirmed P1)

Owns: `PushBindings.install/rebind/on_disconnected` + new `uninstall`,
`HistoryExportService.init/close` wiring, `HistoryService.__init__`
subscription attrs. Touches no other production file.

- `install()` splits into `ensure_browser_binding()` (guarded by
  `host._binding`, called on every reconnect) and
  `ensure_subscription()` (guarded by a new `host._subscribed` flag,
  first install only).
- `rebind()` = clear `_binding` + `ensure_browser_binding()` only.
  Never touches the Python subscription.
- `uninstall()` (new, async, idempotent): `cdp.off_event(
  "Runtime.bindingCalled", host._on_binding)` — bound-method equality
  matches the registered callback — then clears `_subscribed` and
  `_binding`. Duck-typed (`hasattr` guards) like `install()`.
- `init()` becomes idempotent: replace the anonymous `connected`
  lambda with a named `_on_connected` slot; connect Qt signals only
  when not already connected (guard flag, e.g. reuse `_subscribed`
  or a dedicated `_signals_connected`); safe to call after `close()`.
- `close()` unsubscribes first: `await self._push.uninstall()` +
  Qt `disconnect()` of both handlers (guarded with try/except:
  disconnecting a never-connected signal raises), then the existing
  body unchanged. Idempotent (already pinned by
  `test_init_opens_and_close_is_idempotent`).
- `_on_binding` / `on_binding` semantics unchanged (H2 wraps tracking
  *inside* `handle_push`, so H1 does not touch the dispatch path).

Guarantee H1 provides to H2/H3: after `close()` returns, zero history
listeners remain on the CDP client and no Qt reconnect handler survives.
Events dispatched *before* close may still be in flight — H2 owns that.

### 2.2 H2 — In-flight push isolation (P1 investigation + fix)

Owns: `Collector.handle_push` entry/exit + new `drain_pushes()`,
`Collector.__init__` push-tracking attrs, `CollectorRuntime.stop/
restart/start`, `WorldSwitcher` drain call-sites. Deliberately does NOT
touch `HistoryService.__init__`, ` HistoryExportService.close`,
`PushBindings`, or `CDPClient` — all H2 state lives on the `Collector`.

- Tracking: first line of `handle_push` registers
  `asyncio.current_task()` in `collector._inflight` (a set); `finally`
  discards. No CDP change needed — the task already exists, we just
  observe it.
- Gate: new `collector._push_open` flag, checked first in
  `handle_push` (closed → silent `return 0`, no warning). Closed by
  drain entry; re-opened by `CollectorRuntime.restart()` when a
  restart actually happens and by `start()`. `stop()` without restart
  (detach, close, plain stop) leaves pushes closed: stopping the
  collector finally stops push processing.
- Drain: new `Collector.drain_pushes(timeout=...)` — close the gate,
  await `asyncio.wait` on a snapshot of `_inflight` with timeout,
  cancel leftovers, await their suppression, log counts. Called at the
  top of `CollectorRuntime.stop()` (covers `detach_db`, `switch_db`
  via the existing `_stop_collector()` call, and `close()` via its
  first line — no `close()` edit required).
- Race audit (dispatch scheduled-but-not-started vs drain): a push that
  never registers before drain completes starts afterwards and fails
  closed — via `reset_state()` on the switch path (`_nick`/`_verified`
  cleared) and via closed-DB containment on detach/close paths, plus
  the new `_push_open` gate on all paths. Deterministic and testable.
- World token: `collector._world_gen` int, bumped wherever the world
  pointer moves (`_rebind_db` — H2-owned file region) and captured in
  debug logs; defence-in-depth documentation rather than a write-side
  check, because drain-before-rebind removes the interleaving window.
  (A write-side token inside `repo.append` is explicitly rejected:
  it would touch Area B/frozen store code for no additional safety
  once drain exists.)
- Deliverable includes the failing-before test: a push gated
  mid-`append` (event-controlled fake repo or real DB + barrier)
  across a `switch_db` must not write into the new world.

Guarantee H2 provides: when `stop()`/`detach_db()`/`switch_db()`/
`close()` return, zero push tasks are in flight and none can start
writing until the world is ready again.

### 2.3 H3 — Shutdown path hardening (P2)

Owns: `app/lifecycle.py` only. Consumes the H1+H2 `close()` contract
(idempotent; unsubscribes; drains; flushes; closes) without assuming
internals, so it can be built in parallel against fakes.

- Order: `engine.stop()` → `history.close()` (drains + flushes while
  CDP is still up) → `memory.close()` → cancel stragglers (bounded,
  logged) → `cdp.disconnect()` → `app.quit()`. Rationale: persistence
  before teardown; the blanket cancel moves *after* graceful close and
  only reaps tasks close() did not own.
- Every stage wrapped in `asyncio.wait_for` with an explicit timeout
  and a log line naming the stuck stage; `TimeoutError` is logged and
  shutdown proceeds (quit must never hang).
- Keep `_shutdown_started`, keep `bind()` semantics, keep the undo-
  pendings wait (fold it into the staged timeouts).
- Coverage: dedicated shutdown tests (normal order, hung close,
  double shutdown, close raising) — the current weak spot.

## 3. What each area must NOT touch

- `backend/cdp_client.py` — all areas (contract: `on_event` appends,
  `off_event` removes, dispatch schedules awaitables; H1/H2 rely on
  it, nobody changes it).
- `services/db_lifecycle.py`, `bridge/*` — Area A / bridge ownership;
  H2 interacts only through `HistoryService.switch_db/detach_db`.
- `stores/*` — no write-side token, no repo changes.
- `services/history/query.py`, `mutate.py`, `HistoryMigration`,
  `ChatExporter` — unrelated.
- Shared-file discipline: `services/history/runtime.py` is edited by
  H1 (`PushBindings` region) and H2 (`CollectorRuntime`/
  `WorldSwitcher` regions) in disjoint classes; `services/history/
  __init__.py` by H1 only; `services/collector_service.py` by H2
  only; `app/lifecycle.py` by H3 only; `services/history/export.py`
  `close()` by H1 only. Test dir `tests/integration/history_push/`
  with one file per area (no shared helper edits without coordination).
