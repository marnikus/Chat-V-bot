# ChatBot Automator — Architecture Refactor 2026-09-09

**Status:** design + implementation log
**Base commit:** `eadc7e5`
**Companion documents:** `docs/ARCHITECTURE.md` (original design), the
refactoring brief ("Refactor ChatBot Automator — AI Instructions").

The brief is used as *architectural reference*. Everything below is based on
an audit of the code that actually ships in this repository, and where the
brief and reality disagree, reality wins (each deviation is justified in
§10).

---

## 1. Current-state audit (measured, 2026-09-09)

| Area | Measured state | Brief's claim | Verdict |
|---|---|---|---|
| `backend/bridge.py` | **2,478 lines**, ~150 `@Slot` methods, 45 signals, 11+ domains in ONE QObject | bridge monolith | confirmed, worst offender |
| `backend/config_manager.py` | **248 lines** (NOT 1000+ — `preset_store.py` and `label_store.py` were already extracted), but still **7 concerns in one `config.json`**, whole-file non-atomic saves, singleton imported by 6 modules + `main.py` | config god-object | partially confirmed (the *file* is the problem more than the class) |
| `backend/history_service.py` | 867 lines; `collector.py` (776) bypasses the service and calls `history_repo` directly (12 call sites); `media_store` is touched from collector, service AND bridge | service bloat | confirmed |
| `actions/base_action.py` | 89 lines: ABC **and** the global `_REGISTRY` dict. `__init_subclass__` self-registers, but `actions/__init__.py` still keeps a **manual import list of 17 modules**. 28 direct `from backend import …` lines across `actions/` | registry coupling | confirmed (central import list; the dict-on-subclass hook is already half the fix) |
| `ui/js/` | 19 files, 8,231 lines, plain `<script>` tags. **7 copies** of the `DOMContentLoaded`-init boilerplate, confirm modal lives inside `PresetsUI` and is reached from 3 other modules, chip rendering duplicated in `presets-ui` + `url-toolbar` + `sash-grid`, `esc()` duplicated, sort-arrow logic inline | JS duplication | confirmed |
| `ui/css/` | `variables.css` token sheet **already exists** (84 lines) with 500+ `var(--*)` usages; only **26 hard-coded hex values** and some literal radii remain | CSS chaos | mostly already fixed; finishing touches only |
| Async | bridge uses `asyncio.ensure_future` everywhere; services mix `create_task` / `ensure_future` | inconsistency | confirmed |
| DI | `main.py` hand-wires 7 objects; `preset_store` defaults to constructing its own `ConfigManager()` | no DI | confirmed |
| Leftovers | `chatflow/` contains **only `__pycache__/*.pyc`** from an aborted earlier refactor attempt — dead bytecode, no sources | (not mentioned) | delete |
| Tests | 43 Python files ≈ 730 tests (42 files pass headless; `test_sash_webengine.py` needs a real WebEngine), 17 node JS test files — all green at base | — | the safety net for every step below |

Dependency graph today (arrows = "imports"):

```
main.py ──► bridge.py ──► action_engine ──► actions/* ──► backend/*   (upward!)
   │           │  │  └──► preset_store ─┐
   │           │  └────► label_store ───┼──► config_manager (config.json)
   │           └───────► db_manager ────┘        ▲
   └──► history_service ──► collector ──► history_repo, media_store
```

`config.json` mixes: app settings, stack/template presets, URL bookmarks,
custom block presets, the label section (legacy), the undo timeline, and
per-session state — 481 KB of it is committed at the repo root.

## 2. Target architecture

```
main.py                      (DI wiring + app start only)
  │
  ▼
bridge/                      one router + 9 domain bridges (QObjects, @Slot per domain)
  router.py                  exposed to JS as `bridge`; delegates to domain
                             bridges; holds no domain state
  cdp_bridge.py  stack_bridge.py  people_bridge.py  history_bridge.py
  label_bridge.py  db_bridge.py  collector_bridge.py  undo_bridge.py
  layout_bridge.py
  │
  ▼
services/                    business logic; new seams return Result[T]
  people_service.py  undo_service.py  cdp_service.py      (new, extracted from bridge.py)
  run_service.py     history_service.py  db_service.py
  collector_service.py
  │
  ▼
stores/                      pure I/O, one file per store, atomic saves
  jsonio.py  settings_store.py  preset_store.py  bookmark_store.py
  block_store.py  label_store.py  session_store.py  undo_store.py
  migration.py                one-time config.json → config/*.json
  history_repo.py  media_store.py  history_db.py    (moved from backend/)
  │
  ▼
core/                        zero-dependency contracts
  result.py    events.py    interfaces.py    di.py
```

**Dependency rule:** arrows flow DOWN only. A store never imports a service;
a service never imports a bridge; `core/` imports nothing from the app.

## 3. Core contracts (`core/`)

### 3.1 `core/result.py` — Result[T]

`Ok(value)` | `Err(code, detail)`. Helpers: `Result.ok/err`, `Result.of(callable)`
(catches `Exception` → `Err`), `unwrap_or`, `map`. Services at NEW seams
return `Result`; bridges translate `Result` → the existing signal/JSON wire
format, so the JS API is unchanged. `history_service`'s legacy methods keep
their dict returns (documented in §10).

### 3.2 `core/events.py` — EventBus

Pure-Python typed bus: `bus.emit(Event)`, `bus.subscribe(EventType, fn)`,
`bus.unsubscribe`. Synchronous dispatch (order = subscription order).
Domain events (`PeopleChanged`, `PersonFound`, `PersonRemoved`,
`UndoHistoryChanged`, `DbChanged`, `LabelsChanged`, `TabsReceived`,
`ConnectionChanged`, `MyNickChanged`, …) are `dataclass`es in the same
module. Services emit; bridges subscribe and forward to JS via `pyqtSignal`.

Existing Qt signal chains (engine, collector, cdp client) stay connected
directly where they already work — the bus is the seam for the new services,
not a rewrite mandate.

### 3.3 `core/interfaces.py` — Protocols

`typing.Protocol` for every store (SettingsStore, PresetStore, BookmarkStore,
BlockStore, SessionStore, UndoStore, LabelStoreProto, PeopleRepo).
Unit-testable with dict-backed fakes — no filesystem needed.

### 3.4 `core/di.py` — DI container

~40 lines: `container.register(name, factory)`, `container.get(name)` with
singleton caching and cycle detection. `main.py` is the only registrar.

## 4. Config split (`stores/`)

One `config.json` → seven purpose-named files under `config/`:

| File | Contents (old home) | Store |
|---|---|---|
| `config/settings.json` | `chrome`, `scroll`, `delays`, `ui`, `history`, `collector` sections | `settings_store.py` |
| `config/presets.json` | `stack_presets`, `template_presets` | `preset_store.py` |
| `config/bookmarks.json` | `url_presets` | `bookmark_store.py` |
| `config/blocks.json` | `custom_blocks` | `block_store.py` |
| `config/labels.json` | legacy `labels` section (migration source only — the live store is the world DB) | `label_store.py` |
| `config/session.json` | `state.last_url_preset`, `last_stack*`, `block_config_pinned`, `window_states`, `window_geometry`, `db_recent`, `my_nick_recent`, `grid_layout` | `session_store.py` |
| `config/undo.json` | `state.undo_history`, `state.undo_history_index` (app half only; the world half stays in the world's `undo_history` table) | `undo_store.py` |

* **Atomicity**: every save writes `<file>.tmp` then `os.replace`. A failed
  label save can never corrupt presets (different files).
* **Migration** (`stores/migration.py`): on first start, if legacy
  `config.json` exists and `config/` does not, the seven files are written
  and the legacy file is renamed `config.json.migrated-<ts>`. Idempotent;
  a raw-written legacy file is picked up too (tests rely on this).
* **Compatibility**: `ConfigManager` stays as a thin routing facade with its
  current API (`get/set/get_copy/named_*/get_state/set_state/save/validate`,
  `DEFAULTS`, `MAX_STACK_HISTORY`, `_path`). Section access is routed to the
  owning store. The 6 modules + all 43 test files keep working unchanged;
  new code gets stores injected.
* `config/` and `config.json.migrated-*` are runtime data → `.gitignore`.

## 5. Bridge split (`bridge/`)

### 5.1 The mechanism (verified against PySide6)

QWebChannel publishes only the registered object's metaobject. To keep ONE
registered object (`bridge`) — and therefore an **unchanged JS wire API** —
while physically splitting the implementation, `router.py` assembles the
Router class dynamically with `Shiboken.ObjectType`:

* every domain bridge's `@Slot` methods are re-published as forwarding slots
  (same names, same signatures, read from each bridge's `QMetaObject`), and
* every domain signal is re-published on the Router and re-emitted
  (`bridge.<signal>.connect(router.<signal>)`).

Verified in-sandbox: a class built this way publishes slots and signals in
its metaobject exactly like a hand-written QObject subclass.

### 5.2 Domain bridges (all @Slot methods move verbatim from `bridge.py`)

| Bridge | Slots (existing JS names, unchanged) | Signals |
|---|---|---|
| `CdpBridge` | `get_tabs`, `connect_tab`, `find_tab_by_url` | `tabs_received`, `connection_status`, `tab_match_result` |
| `StackBridge` | run/stop/pause/resume, stack+template preset CRUD, custom-block CRUD, composer/criteria get/set, `snapshot_stack`, stack-history compat slots | `preset_list_updated`, `template_list_updated`, `custom_blocks_updated`, `stack_loaded`, `template_loaded`, engine step/complete signals |
| `PeopleBridge` | `refresh_users`, `delete_user(s)`, `set_user_messaged`, `reset_messaged`, `clear_memory` | `users_updated`, `stats_updated`, `users_deleted`, `person_found`, `person_removed` |
| `HistoryBridge` | `history_open/page/search/stats`, `userdb_page/stats`, archive delete/clear/merge/restore/purge, `media_*`, `copy_*`, `open_media_folder` | `history_*_ready`, `userdb_*`, `media_ready`, `history_error` |
| `LabelBridge` | `get_labels`, `label_*` | `labels_changed` |
| `DbBridge` | `db_list/info/create/load/delete/clean` | `db_changed`, `db_info_ready` |
| `CollectorBridge` | `collector_state/set/command`, `get/set_my_nick`, `detect_my_nick`, history settings get/save | `collector_status`, `collector_log`, `history_appended`, `my_nick_changed` |
| `UndoBridge` | `undo`, `redo`, `get_undo_history`, `push_global_history`, `undo/redo_stack`, `undo/redo_grid_layout` | `history_changed` |
| `LayoutBridge` | `get/save/reset_grid_layout`, `get/save_window_states`, `set_block_config_pinned` | `grid_layout_changed`, `grid_layout_persisted` |

Cross-domain effects travel over the `EventBus` (e.g. a DB switch emits
`DbChanged`; PeopleBridge refreshes, LabelBridge re-emits labels,
HistoryBridge clears caches). Orchestration that is inherently ordered
(db op → world restart → undo push) stays in the bridge layer, which calls
services in sequence.

### 5.3 Legacy compatibility (the test suite is the contract)

Tests do all of the following, so the Router must support it:

1. `Bridge(cdp=…, memory=…, criteria=…, engine=…, config=…)` — constructor
   keeps the exact legacy kwargs.
2. `Bridge.__new__(Bridge)` + `QObject.__init__(br)` + manual
   `br._config = …` attribute injection — the Router keeps the same private
   attribute names, backed by a shared `BridgeContext`; assigning
   `br._config` writes through to the context, so lazily-created domain
   bridges see it.
3. Class attributes (`GRID_VERSION`, `WINDOW_IDS`, `_default_grid_tree`,
   `_parse_grid_payload`, `COMMAND_KINDS`, …) are copied into the Router
   namespace from `LayoutBridge`/`UndoBridge`.
4. `class FakeBridge(Bridge)` subclassing — `Shiboken.ObjectType` classes
   are normal Python classes; subclassing works.

`backend/bridge.py` becomes a shim: `Bridge = router.Router`.

## 6. Action system (`actions/`)

`base_action.py` (89 lines, ABC + registry dict) splits into:

* `actions/base.py` — `BaseAction` ABC only (interface: `execute`,
  `to_dict`, `config_schema`, delays).
* `actions/registry.py` — `ActionRegistry` with the `@ActionRegistry.register("ID")`
  decorator and `scan()` via `pkgutil.walk_packages`. Duplicate ids raise at
  import time.
* `actions/context.py` — `ActionContext` dataclass (cdp, memory, engine
  hooks, log/report functions) constructed by the run service per run and
  passed to `execute()` where the engine object goes today (duck-typed —
  existing actions keep working unchanged).
* `actions/__init__.py` — calls `ActionRegistry.scan()`; the manual
  17-module import list is deleted (Open/Closed: drop a file in
  `actions/`, it registers itself).
* `base_action.py` remains as a re-export shim (`BaseAction`, `ActionResult`,
  `get_action_class`, `all_action_ids`) — the engine and tests import it.

`execute()`'s `(user_nick, cdp, engine)` signature is retained for
compatibility; `ActionContext` is the typed seam for new blocks.

## 7. JS consolidation (`ui/js/core/`)

New shared modules (classic scripts exposing `window.*` namespaces, same
pattern the codebase already uses; see §10 for why not full ESM):

* `core/bridge-ready.js` — `BridgeReady(fn)` queue replacing the 7
  `DOMContentLoaded` + QWebChannel handshakes.
* `core/dialog.js` — the in-app confirm/alert modal, moved out of
  `PresetsUI` (its 4 cross-module callers stop reaching into another
  panel's guts; `PresetsUI.confirm` delegates for compatibility).
* `core/ui-helpers.js` — `esc()`, chip/pill renderers, sort-arrow toggle.
* `core/undo-fetch.js` — undo-aware bridge call wrapper.
* `core/event-bus.js` — JS-side typed subscriptions for the re-emitted
  router signals.

Consumers are refactored to import these; node tests are added for each
core module and the existing 17 JS test files must stay green.

## 8. CSS tokens

`variables.css` already carries the token sheet. Finish the job: replace the
remaining 26 hard-coded hex values and literal radii with `var(--*)`
references; no structural reorganisation (no layered `@layer` rewrite — the
cascade is stable and tested by pixel-agnostic JS tests only).

## 9. Async rules

* Coroutines live in services only; stores are synchronous (config) or
  await-only (SQLite stores).
* Bridges use `@asyncSlot` (qasync) for slots that must `await`; plain
  fire-and-forget scheduling goes through one helper, not ad-hoc
  `asyncio.ensure_future` scattered per method.
* `asyncio.gather` stays out of action steps (already sequential).
* Every service boundary I/O returns `Result`; no bare exception crosses a
  layer boundary.

## 10. Deviations from the reference brief (and why)

1. **JS wire API unchanged** — the brief proposes new prefixed method names
   (`backend.cdp_connect`, `stack_run`, …). The shipped JS (8.2k lines, 17
   test files) uses the current names. Splitting Python while renaming the
   wire would double the blast radius for zero functional gain. The Router
   keeps every existing name; a future rename can be mechanical.
2. **Labels live in the world DB, not `config/labels.json`** — the repo's
   own 2026-09-08 design (`DB_CREATION_DELETION_REDESIGN`) moved labels into
   each world file so they die with the world. Regressing them into one
   JSON would violate that design. `config/labels.json` exists only as the
   migration source for legacy installs.
3. **`history_service` is not trimmed to 15 methods by force** — the brief's
   count targets a different codebase state. The split extracts
   people/undo/cdp into real services and moves repo/media/history_db into
   `stores/`; the archive service keeps its cohesive surface. `Result[T]`
   is adopted at the new seams first.
4. **JS stays on classic scripts + window namespaces, not ESM** — the node
   test harness reads and evaluates the shipped files as classic scripts;
   converting 19 files + 17 test harnesses to ESM is high-risk churn with
   no bundler to catch mistakes. `ui/js/core/` is the module boundary going
   forward.
5. **`chatflow/` deleted** — it is dead bytecode (`.pyc` only) from an
   aborted attempt at this same refactor.

## 11. Implementation plan & LOC log

LOC measured with `wc -l`, before → after each step.

| # | Step | Before | After | Δ |
|---|---|---|---|---|
| 0 | delete dead `chatflow/` pycache | 0 py | — | −(dead) |
| 1 | `core/` contracts + tests | 0 | TBD | — |
| 2 | `stores/` config split + migration + facade | TBD | TBD | — |
| 3 | actions registry/context split | TBD | TBD | — |
| 4 | `services/` extraction + moves | TBD | TBD | — |
| 5 | `bridge/` router + 9 domain bridges + shims | TBD | TBD | — |
| 6 | `main.py` DI rewiring | 283 | TBD | — |
| 7 | JS `ui/js/core/` + consumer dedupe | TBD | TBD | — |
| 8 | CSS token completion | TBD | TBD | — |
| 9 | docs + full test suite green | — | — | — |

Every step ends with the full suite green (minus the pre-existing headless
`test_sash_webengine.py` limitation).
