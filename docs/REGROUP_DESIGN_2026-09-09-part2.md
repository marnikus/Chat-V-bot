# Regroup Design — Making Modules Smaller & Reusable
**Date:** 2026-09-09  
**Part:** 2 — After Weak Architecture Audit (219822a)  
**Principles:** SRP, DIP (depend on Protocols), Reusability, <200 LOC per module, Design Doc Before Code

---

## 1. Before — Current Module Map (measured)

| Module | File | LOC | Responsibility | Weakness |
|---|---|---|---|---|
| **God Bridge** | `backend/bridge.py` | 2486 | 94 Slots, 30 Signals, 11 domains | SRP violation, untestable without Qt, merge conflicts |
| **God History** | `backend/history_service.py` | 867 | DB + media + collector + migration + settings + gaze | 42 methods, layer leak |
| **God Engine** | `backend/action_engine.py` | 924 | queue + tracer + label guard + history + phases | 6 concerns, hard to mock |
| **Large Repo** | `backend/history_repo.py` | 1217 | person + message + media + cursor | 2x HistoryService, tightly coupled |
| **Large Collector** | `backend/collector.py` | 776 | owns repo directly, bypasses MediaStore | violates “MediaStore only via HistoryService” |
| **Large DB** | `backend/history_db.py` | 746 | schema + migrations | frozen but large |
| **Parser** | `backend/chat_parser.py` | 644 | scroll + parse + nick detect | mixes parser + scroll |
| **Config Façade** | `backend/config_manager.py` | 142 | delegates to stores but still central | 17 imports, not yet deleted |
| **New stores** | `stores/*.py` | 457 (7 files 43-103) | each owns one JSON slice | ✅ Good — atomic .tmp+fsync+replace, but still share one file |
| **New bridge** | `bridge/*.py` | 1026 (router 136 + 9×71-153) | domain bridges | ⚠️ Side-car, not yet canonical (W1 shim) |
| **New services** | `services/*.py` | 140 (history 78 + collector 56) | facades with `__getattr__` hack | ⚠️ Fake (W4) — leaky, not reusable |
| **Core** | `core/*.py` | 220 (result 72, events 44, di 41, interfaces 56) | shared contracts | ⚠️ Interfaces too small (only 2 methods) |
| **UI JS** | `ui/js/*.js` | 20 files, stack-dnd 1230, sash-grid 1203, app 470 | globals, copy-paste | ⚠️ Core 141 dead, 0 imports |
| **CSS** | `ui/css/*.css` | tokens 54, variables 85, 57 hex left | duplicated vars | ⚠️ Circular vars fixed in W7 |

**Total Python backend:** 25705 LOC. Largest single file = Bridge 9.6% of total, History family (service 867 + repo 1217 + db 746 + query 420 + media 738 + collector 776) = 4764 = 18.5% tightly coupled.

**Dependency graph (before):**
```
main.py → backend/bridge (god) → backend/history_service (god) → history_repo → history_db
         ↘ action_engine (god) → cdp_client, user_memory, criteria
         ↘ config_manager (façade) → stores/atomic (shared file)
ui/js/app.js (global) → copy-pasted bridgeReady/confirm/chip (6 files)
```

---

## 2. After — Regrouped Module Tree (target, each <200 LOC, reusable)

```
core/
  result.py        72  Result[T] — boundary contract, no exceptions
  events.py        44  EventBus  — sync pub/sub, testable without Qt
  di.py            41  Container — ~40 lines, no third-party, 10 keys
  interfaces.py   130  Protocols: Store, SettingsStore, HistoryServiceProto (15 methods),
                         MediaServiceProto, DbServiceProto, CollectorServiceProto, UndoStoreProto
                       — bridges depend on Protocols, not concretes

stores/            457 → 620 (each owns ONE file, isolated AtomicJsonStore + Lock)
  atomic.py        77  AtomicJsonStore — .tmp + fsync + os.replace, pure I/O
  settings_store.py 71  chrome/scroll/delays/ui/history/collector slices
  bookmark_store.py 43  url_presets
  block_store.py    61  stack_presets/template_presets/custom_blocks
  session_store.py  55  state.last_*, window_geometry, block_config_pinned
  undo_store.py     55  state.undo_history + index (seq-aware merge)
  migration.py     103  legacy config.json → new slices, idempotent
  label_store.py    60  (new, wraps backend/label_store via Protocol)
  preset_store.py   60  (new, wraps backend/preset_store via Protocol)

bridge/           1026 → 1026 (now canonical, backend/bridge.py → 20 shim)
  router.py       136  QWebChannel entry, composes 9 domains, @asyncSlot only
  cdp_bridge.py    80  tabs/connect/find_tab_by_url
  stack_bridge.py 138  run/pause/presets/templates/custom_blocks
  people_bridge.py  88  users/stats/refresh/delete/messaged
  history_bridge.py 153  history_open/page/search/stats, Result→Signals
  label_bridge.py   90  labels CRUD + filter
  db_bridge.py      79  db_list/info/create/load/delete/clean
  collector_bridge.py 90  collector_state/set/command
  layout_bridge.py  87  grid_layout/window_states
  undo_bridge.py    71  undo/redo/push_global_history

services/          140 → 380 (real services, coroutines only here, always Result)
  history_service.py 150  15 explicit methods, no __getattr__, delegates to backend/history_service
  media_service.py    80  owns MediaStore via HistoryService, no direct repo
  db_service.py       90  switch_db, load_world_undo, save_world_undo, migrate_install
  collector_service.py 50  tick/backfill/state via HistoryService.collector, no repo
  query_service.py    60  (optional, page/preview_settings/search)
  label_service.py    60  (optional, wraps LabelStore)
  engine/
    queue.py         120  queue_order, queue building, standalone Nick
    tracer.py         80  RunTracer JSONL
    executor.py      200  _execute_cycle, _run_single_target
    label_guard.py    60  allows/reject_reason

backend/ (kept as implementation detail, but each <300 after extraction)
  history_service.py 867 → 300 (trimmed to 15, rest moved to services)
  history_repo.py   1217 → 800 (split person/message)
  history_db.py      746 (frozen schema, Do Not Touch)
  collector.py       776 → 500 (remove repo direct, use MediaService)
  action_engine.py   924 → 200 (coordinator only, delegates to engine/*)

ui/
  js/core/          141 → 300 (now live, imported)
    bridge-ready.js  31  bridgeReady()
    dialog.js        19  showDialog/confirmDialog
    event-bus.js     22  EventBus
    ui-helpers.js    42  qs/qsa/createEl/escapeHtml
    undo-fetch.js    27  fetchUndoHistory/pushUndo
  js/app.js         470 → 350 (−120 dedicated to core imports)
  css/tokens.css     54 → 62 (fixed circular, merged variables)

actions/
  registry.py        83  @register, ActionContext, discover() pkgutil
  base_action.py     89  BaseAction abstract
  15 actions        30-283 each ≤100 after retire keys stripped
```

**Dependency graph (after):**
```
main.py (DI only, 10 keys) → bridge/router → services (Result, coroutines) → stores (atomic, <200 each) → backend impl (frozen)
                                ↘ core/Protocols (DIP, testable without Qt)
ui/js/app.js (type=module) → ui/js/core/* (no bundler, reusable)
actions/* → actions/registry (pkgutil auto-scan, no manual list)
```

**Before/After comparison:**

| Metric | Before | After | Change | Reusability gain |
|---|---|---|---|---|
| Largest file | bridge.py 2486 | backend/bridge shim 20 + bridge/* max 153 | −2332, max 153 | Each domain testable in isolation, reusable in other Qt apps |
| Avg service LOC | 78 (fake) | 80-150 (real) | + but each SRP | HistoryService reusable without Qt, MediaService reusable for any media cache |
| God History methods | 42 | 15 explicit | −27 | New blocks can depend on MediaService without pulling DB |
| Engine LOC | 924 | 200 + 4×~100 | −~300 but decoupled | Queue logic reusable for unit tests without Chrome |
| UI dedup | 6 copy-pastes | 0 (core imported) | −250 | New JS panels import chip/pill from ui-helpers, not copy |
| CSS hex | 57 | 0 (except tokens defs) | −57 | New theme = change tokens.css only |

---

## 3. Step Plan (follow audit Phase A-D, now with regroup details)

**Step 3.1 — Design doc (this file) — LOC 0→280 — Done first, no code**

**Step 3.2 — Services regroup (current PR, keep app running):**
- `core/interfaces.py` 56→130: Add `HistoryServiceProto` 15 methods, `MediaServiceProto` 6 methods, `DbServiceProto` 4 methods, `CollectorServiceProto` cleaned.
- `services/history_service.py` 78→150: Remove `ALLOWED+__getattr__`, add 15 explicit `Result`-wrapped methods, add `query` property, no repo exposure.
- `services/media_service.py` **new 80**: `__init__(history_service)`, `media_base_dir()`, `world_media_dir()`, `folder_for(nick)`, `path_for(ref)`, all `Result`.
- `services/collector_service.py` 56→50: Remove `self._repo`, ensure `no direct repo` (only `self._collector` via history_service), keep `Result`.
- `services/__init__.py` 6→20: Export all three.
- **LOC before 140 → after 280 (+140 but 3 modules instead of 2 fake, each reusable).**

**Step 3.3 — Engine regroup (next PR):**
- Extract `backend/action_engine.py` `RunTracer` → `services/engine/tracer.py` 80, `queue_order` → `services/engine/queue.py` 120, keep `action_engine.py` as 200-line coordinator.
- **LOC 924 → 200 + 80 + 120 + 60 + 200 (coordinator) = 660 (−264, but 5 modules <200).**

**Step 3.4 — UI dedup (already W6, next: app.js 470→350 via core imports):**
- `ui/js/app.js` import `{bridgeReady} from './core/bridge-ready.js'` and `{EventBus}` instead of globals.
- **LOC 470→350 (−120, core 141→ live).**

**Step 3.5 — Bridge per-domain <150 (already 71-153, next: ensure Result mapping):**
- `bridge/history_bridge.py` 153 → ensure every Slot does `result = await service.page(...); if result.is_err: history_error.emit(...); else: history_page_ready.emit(...)`
- **LOC +10 per domain for Result mapper, but testable without Qt.**

---

## 4. Reusability examples (why smaller is better)

- **New block “SEND_BACKGROUND_MESSAGE”:** Only needs `MediaService` + `HistoryService.page` — can be developed and unit-tested with fake `MediaServiceProto` without importing `HistoryService` god or `Bridge`.
- **New JS panel “Quick Labels”:** Import `ui-helpers.js` `createEl` and `dialog.js` `confirmDialog` — no copy-paste, consistent pill style via `tokens.css`.
- **Headless test:** `Container` can `register_instance("history_service", FakeHistoryService())` — no Chrome, no Qt, `ActionEngine` tested via `Queue` module alone.
- **Theme change:** Edit `tokens.css` 62 lines, all 581 `var(--*)` refs update — no hex hunt.

---

## 5. Implementation Process (must for every PR)

- [ ] `wc -l` before/after per file (display)
- [ ] `python -m pytest tests/test_core* tests/test_stores* -q` green (or at least 32)
- [ ] `python -m py_compile` touched files ok
- [ ] `app still runs` — `python -c "import bridge.router; import services.history_service"` ok
- [ ] No `history.db` schema, no `sash-core/js`, `sash-grid.js`, `stack-drag.js`, `cdp_client.py`, `.bat` touched
- [ ] `Result[T]` at boundaries, coroutines in services, `@asyncSlot` in bridges
- [ ] Each module <200 LOC, single responsibility, depends on Protocols not concretes

---

## 6. Risks & Do Not Touch (same as audit)

See `WEAK_ARCHITECTURE_AUDIT_2026-09-09.md` §7. Same Do Not Touch list.

---

*End Part 2. Next: commit this doc, then implement Step 3.2 (services regroup) as described.*
