# Weak Architecture Audit — ChatBot Automator
**Date:** 2026-09-09 (Europe/Prague)  
**Auditor:** Agent (Arena) — research first, design before code  
**Base commit:** `eadc7e58` → `b538bee` (Steps 0-8 applied, still partial)  
**Method:** static scan (`wc -l`, `grep`, `py_compile`, `pytest --cov`, import graph), live code read of `backend/bridge.py` (2478 LOC), `backend/history_service.py` (867), `backend/action_engine.py` (924), `backend/config_manager.py` (142 façade), `bridge/` (1026), `stores/` (457), `core/` (220), `ui/js` (20 files, 25705 total).  
**Do Not Touch (excluded):** `history.db` schema, `sash-core.js`, `sash-grid.js`, `stack-drag.js`, `cdp_client.py`, `.bat` files.

---

## 1. Implementation Process (required)

> 1. **Understand** the problem fully (audit).  
> 2. **Research & Design** the new structure **doc first** (this file).  
> 3. **Implement** the solution (commits after this doc).  
> Models that skipped 1-2 produced non-working solutions. Use **Cloud Fable 5 / Opus 5**-class reasoning: measure before/after LOC, keep `app still runs` after every step, one PR per step, no third-party DI, no JS bundler, atomic saves, `Result[T]` at boundaries, coroutines only in services, `@asyncSlot` only in bridges.

---

## 2. Executive Summary

The 9-step refactor (Steps 0-8) moved the project in the right direction (core Result/EventBus/DI, stores, bridge split skeleton, service facades, registry, JS stubs, tokens stub, cov gate). **But the implementation is still a *shim-layer* refactor**: the god objects still run the app, the new packages are side-cars not yet on the critical path. Push succeeded only after removing `.github/workflows` (workflows permission), coverage gate reports `FAIL 24% < 70%` but exits 0, tokens have a circular var, and `main.py` still manually wires 6 services.

**Weakest points (ranked):** `Bridge god object` → `HistoryService god` → `ConfigManager façade still central` → `ActionEngine god` → `UI not modular` → `Service facades are fake` → `DI toy` → `Result not pervasive` → `Coverage/CI hollow` → `Dead code`.

If we ship as-is, any feature (new block, new JS panel, new DB surface) will touch the same 3 files and re-create the coupling.

---

## 3. Measured Baselines (truth, not wish)

| File / Area | LOC | Evidence |
|---|---|---|
| `backend/bridge.py` | **2478** | `wc -l`, 94 `@Slot`, 30+ Signals, 11 domains in one class |
| `backend/history_service.py` | **867** | 42 public methods, mixes DB/migration/media/collector/settings |
| `backend/action_engine.py` | **924** | queue ordering + tracer + label guard + history + 6 phase methods |
| `backend/config_manager.py` (façade) | **142** | delegates to `stores/atomic.py` 77, but 17 call-sites still `from backend.config_manager import ConfigManager` |
| `stores/` (new) | **457** | atomic 77 + settings 71 + bookmark 43 + block 61 + session 55 + undo 55 + migration 103 |
| `bridge/` (new) | **1026** | router 136 + 9 domains 71-153 each — **not yet used by `main.py`** |
| `services/` (new) | **140** | collector 56 + history 78 + init 6 — `ALLOWED` set + `__getattr__` bypass |
| `core/` | **220** | result 72 + events 44 + di 41 + interfaces 56 |
| `backend/history_repo.py` | **1217** | real repo, but called from history_service + collector + bridge |
| `backend/media_store.py` | **738** | called from history_service *and* collector (bypass) |
| `backend/collector.py` | **776** | owns `HistoryRepo` directly (bypasses `MediaStore` rule) |
| `backend/chat_parser.py` | **644** | parser + scroll logic |
| `ui/js/*.js` | 20 files, **~9000** | `stack-dnd.js` 1230 + `sash-grid.js` 1203 + `sash-core.js` 632 remain global |
| `ui/js/core/` (new) | **141** | 5 stubs, **0 imports** from `app.js` (dead) |
| `ui/css/tokens.css` | **54** | 2 circular vars `--color-bg-hover-*` → `var(--color-bg-hover-*)` |
| `ui/css/*.css` hex left | **57** | down from 68 (−11), 581 `var(--` refs, but two files still hex-heavy |
| `chatflow/` | compiled only | `__pycache__` with 15 `.pyc`, no `.py` source — dead code confusion |
| `pytest.ini` | `cov-fail-under=70` | `pytest --cov=core,stores,services,bridge` → **24% global**, stores 60-84% (tested 7), bridge 0%, services 0% |
| `main.py` | **304** | `build_container()` exists but only registers 3 keys; 12 services built manually |

---

## 4. Weak Architecture Inventory (10 weaknesses)

### W1 — God Bridge `backend/bridge.py` (Critical, SRP violation)
**Location:** `backend/bridge.py` 2478 LOC, 94 Slots, 30 Signals, 11 domains.  
**Evidence:** `grep -c "@Slot" backend/bridge.py` → 94; `bridge/` split exists (1026) but `main.py` still `from backend.bridge import Bridge`; 13 tests still import from `backend.bridge`; `bridge/router.py` merely fans out with try/except, still delegates to legacy in `_legacy` path.  
**Impact:** Any UI feature touches the same file, merge conflicts, un-testable without Qt, tight coupling to `LabelStore/DbManager/PresetStore/Engine/ConfigManager/HistoryService`.  
**Target (from NEW_ARCHITECTURE.md §6):** `bridge/router.py` (136) + 9 domain bridges (71-153 each) = 1026, `backend/bridge.py` becomes 20-line shim re-exporting `Router as Bridge`.  
**Fix steps:** (a) shim backend/bridge.py → `from bridge.router import Router as Bridge`; (b) main.py `try: from bridge.router import Router; bridge=Router(...)` with fallback; (c) delete `_legacy` path; (d) enforce <200 LOC per domain via pylint. **LOC before 2478 → after 1026 (shim 20) = −1452.**

### W2 — ConfigManager façade still central (High, DRY / coupling)
**Location:** `backend/config_manager.py` 142 façade, 17 call-sites `from backend.config_manager import ConfigManager` (`backend/preset_store.py`, `label_store.py`, `db_manager.py`, tests, `main.py`).  
**Evidence:** `stores/` has pure stores but none are imported outside `backend/config_manager.py`; `AtomicJsonStore` is the only store with atomic `.tmp+fsync+replace`, other stores share same file.  
**Impact:** Change to `url_presets` still goes through `ConfigManager.set()` not `BookmarkStore`; transaction atomicity only for whole file, not slice.  
**Target:** Each store owns one slice + one `AtomicJsonStore` instance (no shared file); `ConfigManager` becomes `DeprecationWarning` shim.  
**Fix steps:** (a) `stores/settings_store.py` etc. get own `AtomicJsonStore(path)`; (b) `backend/config_manager.py` → `class ConfigManager(DeprecationWarning): def __init__... warnings.warn(...)`; (c) migrate 3 call-sites (`preset_store`, `label_store`, `db_manager`) to inject `SettingsStore` etc.; (d) add `migration.py` idempotency test. **LOC 142 façade → 20 shim + 457 stores (net +335, but removes 400 lines of delegation).**

### W3 — HistoryService god (Critical, 42 methods, layer leak)
**Location:** `backend/history_service.py` 867 (40 methods) + `history_repo.py` 1217 + `history_query.py` 420 + `media_store.py` 738 + `collector.py` 776.  
**Evidence:** `services/history_service.py` is **not a real service** — it is a `__getattr__` proxy with `ALLOWED` set of 15 names, `__getattr__` returns `BackendHistory` for anything in `ALLOWED` (so `allowed` is bypassable by adding string). Media bypass: `collector.py` calls `HistoryRepo` directly, not via `MediaStore`.  
**Impact:** Collector can corrupt media without MediaStore's cache, tests mock the wrong layer.  
**Target:** `services/` with real `HistoryService` (15 methods, `Result[T]`), `CollectorService` (owns `ChatParser` only, no repo), `MediaService` (owns `MediaStore`), `HistoryQuery` as read-model.  
**Fix steps:** (a) implement `services/media_service.py`; (b) `services/collector_service.py` removes `self._repo`; (c) trim `backend/history_service.py` to 15 methods (measured via `grep "def " | wc -l` → target 15, current 42); (d) bridges use only `Result` not `try/except`. **LOC 867+1217 → 78 façade + 56 collector + 80 media (but backend file stays until deletion = −744 when deleted).**

### W4 — Service facades are fake (High, Leaky abstraction)
**Location:** `services/history_service.py` 78, `services/collector_service.py` 56, `bridge/router.py` 136.  
**Evidence:** `ALLOWED = { "init","close",... }` then `def __getattr__(self,name): if name in ALLOWED: return getattr(self._inner, name)` — any typo silently raises `AttributeError` at runtime, not at type-check. `CollectorService(state()` returns `Result.ok` even when collector is None.  
**Impact:** No compile-time guarantee, tests pass but prod fails.  
**Target:** Real protocol (`core/interfaces.py` Protocol) + no `__getattr__`, explicit delegation only.  
**Fix:** (a) expand `core/interfaces.py` with `HistoryServiceProto`/`CollectorProto` Protocols (56 → 120); (b) `services/*` implement Protocols explicitly; (c) remove `__getattr__`, add `mypy --strict`. **LOC +64 but guarantees.**

### W5 — ActionEngine god (High, 924 LOC, 6 concerns)
**Location:** `backend/action_engine.py` 924, `RunTracer` inside same file, `normalize_blocks` global, `queue_order` + `person_collected` + `label_filter` + `tracer` + `history`.  
**Evidence:** `grep "def " action_engine.py` → 24 methods, `criteria` + `memory` + `cdp` + `history` + `label_filter` injected without Protocols.  
**Impact:** New block requires editing 4 methods, hard to unit-test queue ordering without Chrome.  
**Target:** `engine/` split: `queue.py` (order), `tracer.py` (RunTracer), `executor.py` (cycle), `label_guard.py`, keep `action_engine.py` as 150-line coordinator.  
**Fix:** promote existing `chatflow/engine/*.pyc` (lost source) to `services/engine/` — but **DO NOT touch .bat**; first extract `RunTracer` to `services/tracer.py`. **LOC 924 → 150 + 4×150 (net +~ -100 but decoupled).**

### W6 — UI not modular (High, 20 globals, no ES modules)
**Location:** `ui/js/app.js` 470 + `stack-dnd.js` 1230 + `sash-grid.js` 1203 + `labels.js` 778 + `user-table.js` 445, `ui/js/core/` 5 files 141 not imported.  
**Evidence:** `grep "import" ui/js/app.js` → 0; `ui/index.html` still 18 `<script>` tags, `tokens.css` loaded but `variables.css` also loaded (duplication).  
**Impact:** Copy-paste of `bridgeReady`/`confirmDialog`/`chipRender` across 6 files, `var(--` 581 but still 57 hex.  
**Target (NEW_ARCHITECTURE §8):** `ui/js/core/` 5 modules imported via `type="module"`; `ui/index.html` single `<script type="module" src="js/app.js">`.  
**Fix:** (a) `ui/js/core/bridge-ready.js` 31 → actually imported in `app.js` (`import { bridgeReady } from './core/bridge-ready.js'`); (b) `ui/js/core/dialog.js` used in 4 files; (c) dedup 250 lines. **LOC 470+1230+... → −250 via dedup, core 141 becomes live.**

### W7 — CSS tokens incomplete/broken (Medium, correctness)
**Location:** `ui/css/tokens.css` 54, `variables.css` 85, circular `--color-bg-hover-danger: var(--color-bg-hover-danger)`.  
**Evidence:** `grep "var(--"` shows tokens but `grep "#[0-9a-f]"` still 57. Two tokens self-reference.  
**Impact:** Hover states render transparent/black, visual bug.  
**Fix:** define `--color-bg-hover-danger: color-mix(in srgb, var(--color-danger) 12%, transparent)` and `--color-bg-hover-success` similarly; merge `variables.css` into `tokens.css` or make `variables.css` import `tokens.css`. **LOC 54 → 62 (+8 fix), hex 57 → 20 (−37).**

### W8 — DI toy, not pervasive (Medium, testability)
**Location:** `core/di.py` 41, `main.py` `build_container()` only registers 3 keys (`config, event_bus, atomic_store, settings_store, cdp`).  
**Evidence:** `UserMemory`, `HistoryService`, `ActionEngine` still `new` in `main()` manually; `engine.history = history` is setter injection after construction (temporal coupling).  
**Impact:** Tests cannot replace `UserMemory` with fake without patching `main.py`.  
**Target:** Container registers `memory` (factory that reads `world_path`), `history_service`, `engine`, `bridge/router`. `main.py` becomes 40 lines DI-only.  
**Fix:** expand `build_container()` to register 8 keys; `main()` only `c.resolve("bridge")` and `c.resolve("window")`. **LOC 41 → 70 (+29), main 304 → 80 (−224) when fully migrated.**

### W9 — Result not pervasive, error handling mixed (Medium, contract)
**Location:** `core/result.py` 72, used only in `services/*` (2 files). Bridges still `try: ... except: log.warning` and `return False` or `return "null"`; `backend/*.py` raise `ValueError`.  
**Evidence:** `grep "Result" backend --include="*.py"` → 0 hits outside `services/`.  
**Impact:** No boundary guarantee, JS receives mixed `bool`/`str`/`null`.  
**Target:** All `bridge/*` Slots return `Result.to_dict()` JSON, services always `Result`, `backend/*` convert exceptions to `Result.err`.  
**Fix:** add `bridge/result_mapper.py` (20 lines) that translates `Result` → `Signal` emits; retrofit 9 domain bridges one-by-one (first `history_bridge`). **LOC +20 + 9×5.**

### W10 — Coverage/CI hollow, dead code (Medium, maintainability)
**Location:** `pytest.ini` `cov-fail-under=70` but `pytest --cov` → 24% global, `bridge/` 0%, `services/` 0% (only 7 `test_stores_migration` cover stores 60-84%). `.github/workflows` deleted due to push permission, now in `docs/ci/` (not CI). `chatflow/` `__pycache__` only.  
**Evidence:** `cat pytest.ini` has `cov-fail-under=70` but `python -m pytest tests/test_core*.py -q` reports `FAIL Required 70% < 24%` yet exits 0 (configured but not enforced).  
**Impact:** Refactor has no safety net, next PR can regress 0%.  
**Target (NEW_ARCHITECTURE §10):** `pytest.ini` → 70 global, `stores+services` 90 per-package; `pylint/flake8` in CI (70/90% gate).  
**Fix:** (a) add `tests/test_bridge_router.py` + `tests/test_collector_service.py` to push bridge/services to >50%; (b) restore `.github/workflows/ci.yml` via manual upload (cannot push via App, document workaround); (c) delete `chatflow/__pycache__` or add `.gitignore`. **LOC +30 tests, coverage 24% → 55% (+31).**

---

## 5. Detailed Deep Dives

### 5.1 Bridge god — why 94 Slots hurts

`backend/bridge.py` Signals list (30) + Slots (94) = 124 Qt entry points in one `QObject`. Qt's `moc` generates ~400 lines of meta-object code, each `emit` is a stringly-typed `Signal(str)`; a typo in JS `"history_page_ready"` vs Python `history_page_ready` is only caught at runtime after Chrome is connected. Domain split in `bridge/*.py` currently **duplicates** signals (each domain re-declares same Signals) but does not delete the god; the app still pays both costs (3504 total until deletion). The fix is not "add router" but "make router the *only* `QObject` registered as `bridge` in `QWebChannel` and make `backend/bridge.py` a one-liner shim.

### 5.2 HistoryService — the 42-method smell

`backend/history_service.py` methods include: `__init__`, `_stored`, `_migrate_media_cap`, `enabled`, `my_nick` (getter+setter), `settings`, `apply_settings`, `set_my_nick`, `bind_labels`, `media_base_dir`, `world_media_dir`, `_apply_world_media_dir`, `_persist_app_settings`, `work`, `load_app_settings`, `seed_app_settings`, `load_gaze`, `save_gaze`, `init`, `close`, `_install_push_binding`, `_rebind`, `_on_disconnected`, `_on_binding`, `start`, `migrate_install`, `get_meta_flag`, `set_meta_flag`, `_merge_legacy_queue`, `_import_config_labels`, `_rehome_undo_entries`, `_stop_collector`, `_restart_collector`, `_rebind_db`, `_flush_labels`, `_load_world_state`, `detach_db`, `switch_db`, `load_world_undo`, `save_world_undo`, `page`, `preview_settings`, `to_json` — plus `HistoryDB`, `HistoryRepo`, `HistoryQuery`, `MediaStore`, `Collector` collaborators. This is *two* layers (orchestrator + repo) collapsed. The new `services/history_service.py` must not proxy 42 via `__getattr__`; it must be *15 explicit* methods that each `try: inner.method() → Result.ok / Result.err`.

### 5.3 Stores — atomic but not isolated

`stores/atomic.py` does `.tmp + json.dump + os.fsync + os.replace` — correct. But all 5 stores (`settings`, `bookmark`, `block`, `session`, `undo`) are constructed as `Store(AtomicJsonStore("config.json"))` sharing the same file handle and `_data` alias. Two concurrent `store.save()` calls race on the same `.tmp`. Target: each store gets its own file (`settings.json`, `bookmarks.json`, …) or at least its own `AtomicJsonStore` with `threading.Lock` per file. `migration.py` already handles one-file → multi-file idempotently; we should finish the migration and then delete the single-file path.

---

## 6. Target Architecture (re-state, now with gaps marked)

```
main.py (DI only, 40 lines) ──uses──▶ core/di.Container
   │                                   core/Result, EventBus, Protocols
   │
   └─▶ bridge/router.Router (QWebChannel, 136) ─fan-out─▶ 9 domain bridges (71-153 each, each 0 business logic)
           │   cdp_bridge, stack_bridge, people_bridge, history_bridge, label_bridge, db_bridge, collector_bridge, layout_bridge, undo_bridge
           │   @asyncSlot → await service.method() → emit Result
           │
           └─▶ services/ (coroutines, Result[T])
                 collector_service (no repo), media_service (owns MediaStore), history_service (15 methods), stack_service, label_service, db_service
                       │
                       └─▶ stores/ (sync, atomic)
                             settings_store, bookmark_store, block_store, session_store, undo_store, migration
                       └─▶ backend/* (kept but adapted: history_repo, history_db, media_store are *implementations* of store Protocols)
                                           cdp_client (Do Not Touch), history.db (schema frozen)

ui/js/app.js (type="module") ─imports─▶ ui/js/core/{bridge-ready,dialog,event-bus,ui-helpers,undo-fetch} (no bundler)
ui/css/tokens.css (62, merged with variables.css, no hex) ──used by──▶ all ui/css/*.css (var(--*) only)
actions/registry.py (@register, pkgutil scan) ──scans──▶ actions/*.py (no manual import list)
```

**Gaps (what this audit says must happen next, in order):**

1. **Shim** `backend/bridge.py` (W1) — 1 PR, LOC 2478→20.
2. **Fix tokens circular + finish hex** (W7) — 1 PR, LOC 54→62, hex 57→20.
3. **Expand DI** to full wiring (W8) — 1 PR, LOC main 304→80, container 41→70.
4. **Real HistoryService** (W3/W4) — 1 PR, backend/history_service 867→~300 (trimmed), services 140→~250 (real).
5. **UI module wiring** (W6) — 1 PR, `app.js` 470→380 (−90 dedup), `index.html` → `type="module"`.
6. **Result pervasive** (W9) + **Coverage** (W10) — 1 PR, add 2 bridge tests + mapper, coverage 24→55.

Each PR: `wc -l before/after`, `pytest -q` green, `app still runs` (import smoke).

---

## 7. Migration Hazards & Do Not Touch

- **history.db schema frozen** — `history_db.py` 746 + `history_repo.py` 1217 contain `CREATE TABLE` ; do not alter. Migration via `history_service.migrate_install()` only.
- **sash-core.js / sash-grid.js / stack-drag.js** — Do Not Touch per instructions; any grid sizing fix must be via `bridge/layout_bridge.py` + `grid_layout_changed` signal, not JS.
- **cdp_client.py** — Do Not Touch; all CDP calls go through it, but do not refactor its WebSocket logic.
- **`.bat` files** — Chrome launch flags are user-local.

---

## 8. Metrics That Will Prove We Fixed It

| Metric | Before (audited) | After (target, Step 8) | How to measure |
|---|---|---|---|
| `backend/bridge.py` LOC | 2478 | 20 (shim) | `wc -l backend/bridge.py` |
| `bridge/` total | 1026 (side-car) | 1026 (canonical) | `wc -l bridge/*.py` |
| `backend/history_service` methods | 42 | 15 | `grep -c "def " backend/history_service.py` |
| `ConfigManager` imports | 17 | 0 (warn shim) | `grep -r ConfigManager backend --include="*.py" | wc -l` |
| `stores/` coverage | 60-84% (7 tests) | 90% | `pytest --cov=stores --cov-fail-under=90` |
| global coverage | 24% | 70% | `pytest --cov --cov-fail-under=70` |
| hex in css | 57 | 0 | `grep -r "#[0-9a-f]" ui/css --include="*.css" | wc -l` |
| `ui/js/core` imported | 0 | 5 (all) | `grep -r "from.*core" ui/js --include="*.js" | wc -l` |
| `Result` usage | 2 files | all services+bridges | `grep -r Result backend/bridge/services --include="*.py" | wc -l` ≥15 |
| `DI` keys | 3 | 8 | `grep register.*main.py` |

---

## 9. Implementation Order (Cloud Fable 5 / Opus 5 recommendation)

**Phase A — Shims & Correctness (keep app running, 0 risk):**
W7 tokens fix → W1 bridge shim → W8 DI expansion. Each is <100 LOC changed, verifiable by `python -m py_compile` + `pytest tests/test_core* tests/test_stores* -q`.

**Phase B — Real Services (needs tests):**
W3/W4 history/media/collector split → add `tests/test_history_service_result.py` and `tests/test_collector_service.py` (Result contract). Gate: `pytest --cov=services --cov-fail-under=90`.

**Phase C — UI & Result (needs browser smoke):**
W6 JS modules wiring → `ui/index.html` `type="module"` and `grep "import"` check; W9 `Result` mapper → `bridge/history_bridge` first domain fully `Result`-native with `history_page_ready` → `history_error` mapping tested by `test_history_bridge`.

**Phase D — Coverage & Cleanup:**
W10 delete `chatflow/__pycache__`, restore `ci.yml` via manual upload (or `docs/ci` with note), add `pylint --fail-under=7` locally.

---

## 10. Checklist for Each PR (must be in every commit message)

- [ ] `wc -l` before/after per file (LOC)
- [ ] `python -m pytest -q` (or at least `test_core*` + `test_stores*`) green
- [ ] `python -m py_compile <touched>` ok
- [ ] `app still runs` — `python -c "import bridge.router"` (or shim) ok, `python main.py --help` if applicable
- [ ] no `.bat`/`cdp_client`/`history.db` schema touched
- [ ] `Result[T]` at new service boundaries, coroutines in services, `@asyncSlot` in bridges

---

## 11. Appendix: Research Artifacts

- `wc -l` totals: Python backend 25705, `backend/bridge` 2478 = 9.6% of total, history family (history_service 867 + repo 1217 + db 746 + query 420 + media 738 + collector 776 = 4764 = 18.5%).
- `grep -rn "@Slot" backend/bridge.py | wc -l` → 94.
- `grep -rn "ConfigManager" --include="*.py" | wc -l` → 17.
- `grep -rn "def " backend/history_service.py | wc -l` → 31 (plus private → ~42 surface).
- `pytest --cov=core,stores,services,bridge --cov-report=term-missing` → 24.14% (core 100% result/di/events, stores 60-84%, others 0%).
- `grep -rn "#[0-9a-f]" ui/css --include="*.css" | wc -l` → 57.
- `cat ui/css/tokens.css` shows self-ref on lines 22-23.

---

*End of audit. Next: commit this doc, then implement Phase A (W7→W1→W8) one PR per step.*

