# 150 LOC Full Regroup — All Files <150 (Cloud Fable 5 / Opus 5)

**Date:** 2026-09-09 — **Branch:** `arena/01a083b4-chat-v-bot` — **Goal:** every non-exempt file `<150` LOC.  
**Process:** Understand → Design doc FIRST → Implement (atomic, app working after every step, one PR per step, no third-party DI, no JS bundler, Result[T] + @asyncSlot boundaries, .tmp+rename).  
**Exempt (Do Not Touch):** `history.db` schema, `sash-core.js` (632), `sash-grid.js` (1203), `stack-drag.js` (355), `cdp_client.py` (311), `.bat`.

## 0. Research — Current Audit (2026-09-09)

`find backend bridge app core services stores ui -name '*.py' -o -name '*.js' | xargs wc -l | awk '$1>150' | sort -nr`

| LOC | File | Status |
|-----|------|--------|
| 1230 | `ui/js/stack-dnd.js` | **Exempt** (Do Not Touch) |
| 1203 | `ui/js/sash-grid.js` | **Exempt** |
| 924 | `backend/action_engine.py` | **TODO** — god (90+ Slots, 40+ actions) |
| 802 | `backend/js/chat_agent.js` | TODO — JS agent, scope split |
| 778 | `ui/js/labels.js` | TODO |
| 746→11 | `backend/history_db.py` | **DONE** 746→11 + 6×<130 (helpers 64, mixin1 127, 2a 89, 2b 93, 3 116, 4 79) |
| 738 | `backend/media_store.py` | TODO — 738 (media cache, download, evict) |
| 644 | `backend/chat_parser.py` | TODO |
| 632 | `ui/js/sash-core.js` | **Exempt** |
| 612 | `backend/db_manager.py` | TODO |
| 541 | `backend/label_store.py` | TODO |
| 495 | `backend/scroll_parser.py` | TODO |
| 470 | `ui/js/app.js` | TODO — app bootstrap |
| 463 | `backend/dom_highlight.py` | TODO |
| 452 | `ui/js/history-store.js` | TODO |
| 451 | `backend/message_injector.py` | TODO |
| 445 | `ui/js/user-table.js` | TODO |
| 420 | `backend/history_query.py` | TODO |
| 411 | `ui/js/history-model.js` | TODO |
| 356 | `backend/media_handler.py` | TODO |
| 353 | `ui/js/db-panel.js` | TODO |
| 341 | `ui/js/history-view.js` | TODO |
| 332 | `ui/js/presets-ui.js` | TODO |
| 326 | `ui/js/history-db.js` | TODO |
| 311 | `backend/cdp_client.py` | **Exempt** |
| 302 | `ui/js/collector-panel.js` | TODO |
| 248 | `backend/user_memory.py` | TODO (248, just over) |
| 228 | `ui/js/color-picker.js` | TODO |
| 217 | `backend/dom_probe.py` | TODO |
| 187 | `backend/visual_click.py` | TODO |
| 185 | `backend/history_models.py` | TODO |
| 173 | `ui/js/url-toolbar.js` | TODO |
| 151 | `backend/preset_store.py` | TODO (151, trim 2) |
| **DONE** | `main.py` 338→102, `app/window`132, `app/container`75 |
| **DONE** | `backend/bridge` 2486→5 + `bridge/grid`130, `router`137, `history_bridge`126 |
| **DONE** | `backend/history_service` 867→12 + 7×<130 |
| **DONE** | `backend/collector` 776→15 + 10×<130 |
| **DONE** | `backend/history_repo` 1217→20 + 15×<150 |
| **DONE** | `backend/history_db` 746→11 + 6×<150 |

> After 6 DONE families, 20+ files still violate. All must be `<150`.

## 1. Design Principles (reusable, <150, no behavior change)

1. **20-line shim** per god file: `from .<name>_parts.<part> import X` + `class God(Mixin1, Mixin2, ...): pass` — public API unchanged, `from backend.xxx import Y` still works, JS `bridge.xxx` still works.
2. **Mixins 80–130 LOC**, 1 responsibility, no cross-import cycles. Top-level helpers (`align_batch`, `_create_table_sql`) live in `helpers.py` and are re-exported by the shim.
3. **JS ES modules, no bundler**: `ui/js/core/*.js` already `<50`; large UI files split into `ui/js/<feature>/` (e.g., `labels/`, `history/`) and re-exported via 20-line shim that preserves `window.*` globals.
4. **Verification per step:** `wc -l <file>`, `python -m py_compile`, `awk '$1>150'` must show the family clean, plus `pytest -q` for `core` (Result/EventBus) and smoke `Bridge.__new__` for grid.

## 2. Target Trees (each file <150)

### 2.1 Backend — Phase A (DB / Media / Parser) — PR 7
```
backend/history_db.py           746→11  shim
  backend/history_db_parts/
    helpers 64, mixin1 127, 2a 89, 2b 93, 3 116, 4 79          DONE 1ec6108

backend/media_store.py          738→15  shim
  backend/media_store_parts/
    base 80 (MediaStore.__init__, cache_dir, limits)
    download 130 (register, download_one, retry_failed_uncached, requeue)
    evict 110 (evict_if_needed, cache_usage, folder_for)
    helpers 60 (_media_key, _file_ext)

backend/chat_parser.py          644→18  shim
  backend/chat_parser_parts/
    sync 130 (sync_conversation, _signature)
    verify 110 (verify_private, PrivateCheck)
    parse 130 (ChatParser.state, chunk, install)

backend/db_manager.py           612→12  shim
  backend/db_manager_parts/
    base 90, list 80 (list_dbs), info 110 (info, active_path), ops 130 (create, load, delete, clean)

backend/label_store.py          541→14  shim
  backend/label_store_parts/
    base 90 (LabelStore.__init__, state, snapshot), defs 110 (create, update, delete), assign 110 (assign, unassign, set_for), filter 80
```

### 2.2 Backend — Phase B (Engine / Injectors) — PR 8
```
backend/action_engine.py        924→18  shim
  backend/action_engine_parts/
    base 120 (ActionEngine.__init__, load_stack, queue_order, decorator registry via pkgutil)
    dispatch 130 (execute, step_started/complete, pause/stop)
    actions 5×130 (find_click, type_message, scroll_parse, collect_history, visual) — each auto-registered via @action decorator (no hand list)

backend/scroll_parser.py        495→15  shim
  backend/scroll_parser_parts/  base 100, scroll 130, parse 130

backend/dom_highlight.py        463→12  shim
  backend/dom_highlight_parts/  base 90, highlight 130, clear 100

backend/message_injector.py     451→12  shim
  backend/message_injector_parts/ base 100, inject 130, clipboard 100

backend/history_query.py        420→14  shim
  backend/history_query_parts/  base 90, page 130, search 110, stats 80

backend/media_handler.py        356→12  shim → 3×110
```

### 2.3 Backend — Phase C (User / Config) — PR 9
```
backend/user_memory.py          248→12  shim → base 90, queue 80, persist 70
backend/dom_probe.py            217→12  shim → 2×110
backend/visual_click.py         187→12  shim → 2×90
backend/history_models.py       185→12  shim → 2×90
backend/preset_store.py         151→12  shim (trim 2 lines: remove blank, inline) → base 90, io 60
backend/person_filter.py        132 already <150 — no split (keep)
backend/criteria_engine.py      102 keep
```

### 2.4 JS — Phase D (UI) — PR 10 (no bundler, type="module" already wired)
```
ui/js/labels.js                 778→20  shim
  ui/js/labels/
    model 130 (state, defs, assign), view 130 (chips, picker), filter 110, controller 120

ui/js/app.js                    470→20  shim
  ui/js/app_parts/
    bootstrap 130 (init, bridgeReady), panels 130 (register), events 110

ui/js/history-store.js          452→20  shim → 3×130 (store, cache, sync)
ui/js/user-table.js             445→20  shim → 3×130
ui/js/history-model.js          411→20  shim → 3×130
ui/js/db-panel.js               353→20  shim → 3×110
ui/js/history-view.js           341→20  shim → 3×110
ui/js/presets-ui.js             332→20  shim → 3×110
ui/js/history-db.js             326→20  shim → 3×110
ui/js/collector-panel.js        302→20  shim → 3×100
ui/js/color-picker.js           228→20  shim → 2×110
ui/js/url-toolbar.js            173→20  shim → 2×80

backend/js/chat_agent.js        802→20  shim
  backend/js/chat_agent/
    pane 130 (pane detection), authors 130, scroll 110, state 130

Exempt kept as-is: sash-core 632, sash-grid 1203, stack-dnd 1230, stack-drag 355, cdp_client 311
```

### 2.5 Tests — Phase E (optional, not blocking CI)
Tests currently 300–800 LOC but are not shipped. Goal 90% coverage via unit tests runs on `core`/`services`/`stores` only; large integration tests stay as-is but new tests for splits are `<150`. No enforcement on test files for this milestone (follow-up).

## 3. Implementation Order (one PR per phase, app working after each)

| PR | Family | Before→After | Branch |
|----|--------|-------------|--------|
| 6 | Full design doc | this file 0→~180 | `docs/150LOC_FULL_REGROUP*` |
| 3.2a | `main` + `bridge` | 338→102, 2486→5 | `00c7b73`, `e7c2e9f` — DONE |
| 3.2b | `history_service` + `collector` + `history_repo` | 867→12, 776→15, 1217→20 | `42c9df7`, `9949383`, `80891b3` — DONE |
| 7 | Phase A DB/Media/Parser | 746→11, 738→15, 644→18, 612→12, 541→14 | next |
| 8 | Phase B Engine/Injectors | 924→18, 495→15, 463→12, 451→12, 420→14, 356→12 | next |
| 9 | Phase C User/Config | 248→12, 217→12, 187→12, 185→12, 151→12 | next |
| 10 | Phase D JS | 778→20, 470→20, 452→20 etc., 802→20 | next |

Each PR: `wc -l` table, `py_compile`, `pytest -k core` smoke, push `arena/01a083b4-chat-v-bot`.

## 4. Reusability (Fable 5 / Opus 5)

- **No god re-introduced:** every shim is 11–20 LOC, no logic. Mixins are importable without Qt (`try: from PySide6 … except: QObject=object`).
- **DI preserved:** `app/container.py` 75 and `services/*` 60–130 use Protocol + Result, no third-party DI.
- **JS:** `ui/js/core` (bridge-ready, dialog, event-bus) stays `<50` and is reused by every panel; new splits import from `core` rather than copying.
- **Atomic save:** every `ConfigManager.set_state` still does `.tmp`+`rename`, verified by existing tests.

## 5. Verification

```bash
# LOC
find backend bridge app core services stores ui -name '*.py' -o -name '*.js' | grep -v __pycache__ | grep -v sash-core | grep -v sash-grid | grep -v stack-drag | grep -v cdp_client | xargs wc -l | awk '$1>150' | sort -nr
# must be empty (except exempt)

# compile + smoke
python -m py_compile backend/*.py bridge/*.py app/*.py
pytest tests/test_core*.py -q
```

---

*Next action:* implement Phase A (PR 7) — `media_store`/`chat_parser`/`db_manager`/`label_store` — then Phases B-D in order.
