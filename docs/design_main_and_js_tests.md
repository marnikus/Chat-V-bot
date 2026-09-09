# Design: `main.py` smoke + JS wire contracts

Written **before** treating function bodies as the spec. Paths below are
what the entry point *must* do for a desktop session to be usable.

## G. `main.py` — expected paths (P0)

| Path | Trigger | Must happen | Failure mode to catch |
|---|---|---|---|
| P-start | `main()` | Qt app constructed with `setQuitOnLastWindowClosed(False)`; qasync loop installed; logger set up | Process dies on last window before async cleanup |
| P-di | `build_container()` | Registers **exactly** these lazy keys: `config`, `bus`, `cdp`, `memory`, `criteria`, `engine`, `history`, `bridge`. Factories receive the container. Nothing built until `get`. | Missing key / eager construction / circular get |
| P-queue | `_queue_path(config)` | If CWD (or install) still has legacy `chatbot.db`, queue lives there; else `config.get("history","db_path")` (default `history.db`) | Always world path while leftover `chatbot.db` exists → split-brain people queue |
| P-registry | engine construction / process start | All shipped action `block_id`s are in `ActionRegistry` (package scan). `main` need not call `scan()` itself **if** engine/actions import does. | Engine starts with empty registry |
| P-db | `startup()` | `memory.init()` then `history.init()` + `history.start()`; history failure is **warning**, not crash; then `bridge.sync_world_state()` | Unhandled exception on missing archive; skipped memory init |
| P-ui | after DI | `MainWindow(config)`, `bridge.attach_history(history)`, `set_bridge`, WebChannel object name `"bridge"`, load `ui/index.html` | Wrong channel name / missing HTML |
| P-geo | window construct / close | Restore only when `window_geometry` is a dict with int x,y,width,height and width,height > 0; save exact geometry on first close | Corrupt state crashes; zero size applied |
| P-close | `closeEvent` | 1st close: ignore, save geo, request grid flush. 2nd while flush pending: ignore. After `_finish_close`: accept, emit `closing`, start 3s watchdog. Flush timeout / JS false / missing page → still finish. Double `_finish_close` is no-op. | Hang on close; double emit shutdown; skip save |
| P-shutdown | `closing` | `engine.stop()`, await undo pendings ≤2s, cancel other tasks, `cdp.disconnect`, `history.close`, `memory.close`, `app.quit`. Idempotent. Exceptions logged, still quit. | Second close double-closes DBs; cancelled undo dropped silently without wait |
| P-exit | loop ends | return 0, log clean exit | `sys.exit` inside `main` (should be caller) |

Tests **must not** copy production branches; they drive the real `main` module
through a Qt stub (no display) and assert observable state.

## H. JS wire tests — contracts (P1/P2)

Existing Node tests stay. Add **missing** files called out by the coverage map:

- `tests/test_bridge_router.js` — if no router module, assert WebChannel
  object name and `bridge.*` methods the UI calls (from `ui/js/app.js`).
- `tests/test_grid_persistence.js` — `SashGrid.flushPersistence` /
  `StackDnD.flushPersistence` exist and return boolean-ish; this is the
  contract `MainWindow._request_grid_flush` JS snippet depends on.

Do not re-assert the same sash-core cases already in `test_sash_core.js`.
