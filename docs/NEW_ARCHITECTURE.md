# Refactor Design — ChatBot Automator (Target Architecture)

**Date:** 2026-09-09  
**Status:** Design for Steps 1-8  
**Base commit:** eadc7e58

## 1. Goals

- Eliminate god-object `config_manager.py` (248 LOC, 7 concerns) and monolith `bridge.py` (2478 LOC, 94 @Slots, 11 domains).
- Enforce downward-only arrows: `main.py (DI) → bridge/router + 9 domain bridges → services (Result[T]) → stores (pure I/O, atomic JSON saves)`.
- No new third-party DI or JS bundler; atomic saves via `.tmp` + `rename`; `Result[T]` across boundaries; coroutines only in services, `@asyncSlot` in bridges.

## 2. Measured Baselines (Step 0)

| File | LOC |
|---|---|
| `backend/config_manager.py` | 248 |
| `backend/bridge.py` | 2478 |
| `backend/history_service.py` | 867 |
| `actions/base_action.py` | 89 |
| `main.py` | 283 |
| **Total** | **3965** |

- `ConfigManager` imports: 17 locations
- `bridge.py` @Slots: 94
- `history_service.py` public methods: ~42 (trim target ~15)

## 3. New Layer Diagram

```
main.py — DI container only (builds Services, wires QWebChannel)
   │
   ├─ core/  (Result, EventBus, Protocols, DI)
   │
   └─ bridge/
        ├─ router.py  (QWebChannel router, signal fan-out)
        ├─ cdp_bridge.py
        ├─ stack_bridge.py
        ├─ people_bridge.py
        ├─ history_bridge.py
        ├─ label_bridge.py
        ├─ db_bridge.py
        ├─ collector_bridge.py
        ├─ undo_bridge.py
        └─ layout_bridge.py   (9 domain bridges)
             │
             └─ services/  (async, return Result[T])
                  ├─ collector_service.py  (no direct repo calls)
                  ├─ history_service.py (trimmed to ~15 methods)
                  ├─ stack_service.py
                  ├─ label_service.py
                  └─ db_service.py
                       │
                       └─ stores/  (sync, pure I/O, atomic save)
                            ├─ settings_store.py
                            ├─ bookmark_store.py
                            ├─ block_store.py
                            ├─ session_store.py
                            ├─ undo_store.py
                            ├─ label_store.py (adapted)
                            └─ migration.py
```

## 4. Core Contracts (`core/`)

### 4.1 `core/result.py` — `Result[T]`

```python
@dataclass(frozen=True)
class Result(Generic[T]):
    ok: bool
    value: T | None
    error: str | None
    @staticmethod def ok(value: T) -> Result[T]
    @staticmethod def err(error: str) -> Result[T]
    def unwrap(self) -> T: ...
    def is_ok(self) -> bool: ...
```

- Never raise across layer boundaries; services always return `Result`.
- Bridges translate `Result.err` → `history_error`/`log_message` signals.

### 4.2 `core/events.py` — `EventBus`

- Sync pub/sub, no asyncio. Methods: `on(event, handler)`, `off(event, handler)`, `emit(event, payload)`.
- Used inside services for `collector_status`, `userdb_changed` etc., before fan-out to Qt signals.
- Isolates Qt signal graph from Python logic for testability.

### 4.3 `core/interfaces.py` — `typing.Protocol`

```python
class Store(Protocol):      load() -> dict
                           save(data: dict) -> Result[None]
class SettingsStore(Protocol): get(*keys) -> Any ...
class HistoryServiceProto(Protocol): async def page(...) -> Result[dict] ...
```

- One Protocol per store/service; bridges depend only on Protocols, not concrete classes.

### 4.4 `core/di.py` — Container (~40 lines)

```python
class Container:
    def __init__(self): self._factories = {}; self._singletons = {}
    def register(self, key, factory, singleton=True): ...
    def resolve(self, key): ...
    def register_instance(self, key, instance): ...
```

- No external library; explicit `register` calls in `main.py`.

## 5. Stores (`stores/`)

Each store owns **one** JSON slice + one file, atomic save:

```python
def _atomic_save(path, data):
    tmp = path + ".tmp"
    json.dump(data, open(tmp, "w"), indent=2)
    os.replace(tmp, path)
```

| Store | File slice | LOC budget |
|---|---|---|
| `settings_store.py` | `chrome`, `scroll`, `delays`, `ui`, `history`, `collector` | ~80 |
| `bookmark_store.py` | `url_presets` | ~60 |
| `block_store.py` | `stack_presets`, `template_presets`, `custom_blocks` | ~90 |
| `session_store.py` | `state.last_*`, `window_geometry`, `block_config_pinned` | ~70 |
| `undo_store.py` | `state.undo_history`, `undo_history_index` (seq-aware merge) | ~110 |
| `label_store.py` | wraps existing `backend/label_store.py` via Protocol | ~40 shim |
| `migration.py` | reads legacy `config.json` → new slices, idempotent | ~120 |

`ConfigManager` becomes a façade that delegates to these stores until Step 2 deletion.

## 6. Bridge Split (`bridge/`)

- `router.py`: creates `QWebChannel`, registers each domain bridge as separate `QObject`, exposes `bridge` object that proxies to router for backward-compat.
- Each domain bridge: ~150-300 LOC, one Qt `Signal` group, slots returning `Result` JSON, no business logic.
- `HistoryService` trimmed: `load/store` helpers stay, but `collector` bypass (direct repo calls) removed — `CollectorService` mediates.

## 7. Services (`services/`)

- All `async` methods return `Result[T]`.
- No `asyncio.gather` in actions; no `create_task` outside services/bridges.
- `CollectorService` owns `ChatParser` + `HistoryRepo` interaction; history reads go via it.
- Bridges use `@qasync.asyncSlot` to `await service.method()` and emit Qt signals.

## 8. UI (`ui/js/core/` + `ui/css/tokens.css`)

| `ui/js/core/` | Extracted pattern |
|---|---|
| `bridge-ready.js` | `bridgeReady(callback)` — QWebChannel ready queue |
| `dialog.js` | `confirmDialog(message)` — shared confirm modal |
| `ui-helpers.js` | `chipRender`, `pillRender`, `sortArrows` |
| `undo-fetch.js` | `undoFetch(req_id)` — history pagination + undo stack sync |
| `event-bus.js` | tiny JS `EventBus` mirroring Python one |

- ES modules (`type="module"`), no bundler; `ui/js/app.js` imports via `import { bridgeReady } from './core/bridge-ready.js'`.
- `ui/css/tokens.css` defines `:root { --color-bg: #...; --radius: 8px; --shadow: ... }`; every `*.css` replaced `#[hex]` → `var(--*)` in Step 7.

## 9. Action Registry (`actions/`)

- `actions/base_action.py` split: `registry.py` holds `_REGISTRY` + `@register` decorator + `pkgutil` scan.
- `ActionContext` dataclass (`cdp`, `memory`, `criteria`, `engine`, `user_nick`).
- No manual import list; `all_action_ids()` scans `actions/` at import time.

## 10. Step Plan & LOC Budgets

| Step | Title | New LOC | Deleted LOC | Net |
|---|---|---|---|---|
| 0 | Baselines | +20 (docs) | 0 | +20 |
| 1 | `core/` + stubs + tests | +350 | 0 | +350 |
| 2 | `stores/` + migration, delete `config_manager.py` | +500 | -248 | +252 |
| 3 | `bridge/router` + 9 bridges, delete `bridge.py` | +2200 | -2478 | -278 |
| 4 | `CollectorService`, trim `HistoryService` to ~15 methods | +200 | -300 | -100 |
| 5 | `@ActionRegistry.register` + scan | +80 | -40 | +40 |
| 6 | ES modules `ui/js/core/` | +300 | -250 (dedup) | +50 |
| 7 | `tokens.css` | +120 | -80 (hex replace) | +40 |
| 8 | `pytest-cov --cov-fail-under=70`, CI | +30 | 0 | +30 |

Target totals: Python ~3400 (-500 vs original), JS ~9500 (-1200 via dedup), CSS ~1400 (+120 tokens - 80 hex).

## 11. Verification per Step

- `python -m pytest -q` must stay green after every step.
- `python main.py --help` / import smoke test must not crash.
- `pylint`/`flake8` on new modules < 5 warnings.

## 12. Do Not Touch

`history.db` schema, `sash-core.js`, `sash-grid.js`, `stack-drag.js`, `cdp_client.py`, `.bat` files — excluded from refactor.
