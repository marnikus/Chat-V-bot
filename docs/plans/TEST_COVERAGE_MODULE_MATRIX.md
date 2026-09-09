# 🗺️ Test Coverage Module Matrix — Full Inventory & Design Mapping

> **Companion to:** `docs/TEST_COVERAGE_REF_DESIGN_2026-09-09.md`  
> **Purpose:** Phase 1 (Inventory) + Phase 4 (Smell Classification) + Phase 5 (Architecture Review)  
> **Status:** Design — not yet fully executed (Phase 3 in progress)

---

## Legend

| Symbol | Meaning |
|---|---|
| 🟢 | Covered (existing tests) — needs maintenance |
| 🟡 | Partially covered — expand needed |
| 🔴 | Uncovered — critical; must have test before refactor |
| ⬛ | N/A — pure data / config / generated |

---

## A. `core/` — Contract Layer

| Module | Lines (est) | Functions | Status | Existing Tests | Design Target | Priority |
|---|---|---|---|---|---|---|
| `core/result.py` | 106 | 12 | 🔴 → 🟢 (starter) | `test_core_contracts.py` (partial) | **100% branch** — all `Ok`/`Err`/`of`/`aof` | **P0** |
| `core/di.py` | 77 | 6 | 🔴 | None direct | Unit + integration (graph, cycle, resolve) | **P0** |
| `core/events.py` | 200 | 15 | 🔴 | None direct | Unit (subscribe/emit/unsubscribe) + async | **P0** |
| `core/interfaces.py` | 106 | 10 | 🟡 | `test_core_contracts.py` | Contract assertions | **P1** |

---

## B. `actions/` — Execution Layer

| Module | Lines | Functions | Status | Existing Tests | Design Target | Priority |
|---|---|---|---|---|---|---|
| `actions/registry.py` | 110 | 10 | 🟡 → 🟢 (starter) | `test_action_registry.py` | 100% branch — duplicate, shadow, scan, clear | **P0** |
| `actions/base_action.py` | 82 | 5 | 🔴 | `test_action_registry.py` (indirect) | Unit (execute flow, context, error) | **P0** |
| `actions/base.py` | 160 | 12 | 🟡 | Partial via actions | Unit (base behavior) | **P1** |
| `actions/click_user.py` | 182 | 15 | 🟡 | `test_click_user_memory.py`, `test_click_user_order.py` | Integration — order, memory, find, edge (not found) | **P1** |
| `actions/scroll_parse.py` | 145 | 10 | 🟡 | `test_scroll_parse_pipeline.py` | Unit + integration — delta, corrupt, max-depth | **P1** |
| `actions/type_message.py` | 92 | 7 | 🔴 | None | Unit — payload, inject, failure | **P1** |
| `actions/wait_page.py` | 67 | 5 | 🔴 | None | Unit — timeout, condition met, never met | **P1** |
| `actions/pause.py` | 32 | 3 | 🔴 | None | Unit — resume, cancel | **P2** |
| `actions/collect_history.py` | 95 | 8 | 🟡 | `test_collect_history_block.py` | Integration — empty, duplicate, block match | **P1** |
| `actions/search_users.py` | 80 | 6 | 🔴 | `test_search_users.py` (exists?) | Unit — filter, empty result, partial match | **P1** |
| `actions/custom_find.py` | 140 | 12 | 🔴 | None | Unit — find rules, fallback | **P2** |
| `actions/attach_image.py` | 95 | 7 | 🟡 | `test_attach_image.py` | Integration — missing file, corrupt, success | **P1** |

---

## C. `backend/` — Engine & Parser

| Module | Lines | Functions | Status | Existing Tests | Design Target | Priority |
|---|---|---|---|---|---|---|
| `backend/chat_parser.py` | 469 | 35 | 🟡 | `test_chat_parser_delta.py` | Integration — delta, entity, corrupt, concurrent | **P0** |
| `backend/action_engine.py` | 155 | 10 | 🔴 | `test_engine_standalone_run.py` (indirect) | Integration — sequence, rollback, failure stop | **P0** |
| `backend/db_manager.py` | 282 | 20 | 🟡 | `test_db_manager.py` | Unit — open/close, migrate, corrupt, concurrent | **P0** |
| `backend/config_manager.py` | 203 | 15 | 🔴 | None direct | Unit — load, merge, missing, invalid | **P0** |
| `backend/criteria_engine.py` | 95 | 10 | 🔴 | None | Unit — all operators, compound, empty | **P1** |
| `backend/scroll_parser.py` | 472 | 30 | 🟡 | `test_scroll_parse_pipeline.py` | Integration — block detect, boundary | **P1** |
| `backend/dom_highlight.py` | 250 | 15 | 🟡 | `test_find_click_visual.py` | Unit — highlight, remove, selector | **P1** |
| `backend/dom_probe.py` | 120 | 10 | 🔴 | None direct | Unit — probe, element, nil | **P1** |
| `backend/visual_click.py` | 95 | 8 | 🟡 | `test_find_click_visual.py` | Integration — confirmation pass/fail | **P1** |
| `backend/history_db.py` | 15 | 2 | ⬛ | `test_db_migration.py` (indirect) | Integration — schema | **P2** |
| `backend/history_models.py` | 14 | 3 | ⬛ | `test_db_schema_migration.py` | Unit — model validation | **P2** |
| `backend/history_query.py` | 437 | 30 | 🟡 | `test_history_query.py` | Unit + integration — complex query, pagination, empty | **P1** |
| `backend/history_repo.py` | 230 | 15 | 🟡 | `test_history_repo.py` | Integration — CRUD, version | **P1** |
| `backend/history_service.py` | 380 | 25 | 🔴 | None direct | Integration — aggregate, filter, export | **P0** |
| `backend/media_handler.py` | 195 | 15 | 🟡 | `test_media_recovery.py`, `test_media_recovery_e2e.py` | Integration — recovery, missing, path | **P1** |
| `backend/media_store.py` | 130 | 10 | 🟡 | `test_media_store.py` | Unit — path, duplicate, limit | **P1** |
| `backend/message_injector.py` | 350 | 25 | 🔴 | `test_message_block_composer.py` (indirect) | Integration — inject, format, failure | **P1** |
| `backend/person_filter.py` | 95 | 8 | 🔴 | `test_person_filter.py`? | Unit — include, exclude, empty | **P2** |
| `backend/preset_store.py` | 16 | 2 | ⬛ | None | Unit — load/default | **P2** |
| `backend/label_store.py` | 25 | 3 | ⬛ | `test_labels_ui_js.js` (JS only) | Integration — label contract | **P2** |
| `backend/tab_matcher.py` | 130 | 10 | 🔴 | None | Unit — match, fallback | **P2** |
| `backend/user_memory.py` | 32 | 3 | 🔴 | `test_click_user_memory.py` | Unit — graph, cycle, missing | **P2** |

---

## D. `bridge/` — Wire / Boundary

| Module | Lines | Functions | Status | Existing Tests | Design Target | Priority |
|---|---|---|---|---|---|---|
| `bridge/router.py` | 330 | 25 | ✅ | `test_bridge_router.py`, `test_bridge_router_rules.py` | Integration — rules, fallback, cycle | **P0** |
| `bridge/stack_bridge.py` | 245 | 20 | ✅ | `test_stack_dnd_migration.js` (JS), `test_stack_bridge_contract.py` | Integration — push/pop/undo/state sync | **P1** |
| `bridge/undo_bridge.py` | 130 | 10 | ✅ | `test_merge_undo_enabled.py` (indirect), `test_undo_bridge.py` | Unit — command, redo, empty | **P1** |
| `bridge/history_bridge.py` | 300 | 20 | ✅ | `test_history_bridge.py`, `test_history_bridge_wire.py` | Integration — sync, lazy, refresh | **P1** |
| `bridge/label_bridge.py` | 125 | 10 | ✅ | `test_labels_ui_js.js` (JS), `test_label_bridge.py` | Integration — assign/edit/delete contract | **P2** |
| `bridge/layout_bridge.py` | 145 | 12 | ✅ | `test_layout_bridge.py` | Integration — layout sync, resize | **P2** |
| `bridge/people_bridge.py` | 120 | 10 | ✅ | `test_people_undo.py` (indirect), `test_people_bridge.py` | Integration — people sync, undo | **P2** |
| `bridge/cdp_bridge.py` | 95 | 8 | ✅ | `test_cdp_events.py` (indirect), `test_cdp_bridge.py` | Unit — event, disconnect | **P2** |
| `bridge/db_bridge.py` | 110 | 8 | ✅ | `test_db_bridge.py` | Integration — DB sync, transaction | **P2** |
| `bridge/collector_bridge.py` | 55 | 5 | ✅ | `test_collector_state.py` (indirect), `test_collector_bridge.py` | Integration — collector state | **P2** |

> Section D completed 2026-09-09: 109 new tests per
> `docs/plans/BRIDGE_TESTS_DESIGN_2026-09-09.md`; 5 wire bugs found and
> fixed (run_stack non-list wipe, 4 signal self-echo families).

---

## E. `services/` — Orchestration

| Module | Lines | Functions | Status | Existing Tests | Design Target | Priority |
|---|---|---|---|---|---|---|
| `services/run_service.py` | 900 | 60 | 🔴 | `test_engine_standalone_run.py` (indirect) | Integration — loop, state, error recovery | **P0** |
| `services/collector_service.py` | 420 | 30 | 🟡 | `test_collector_state.py`, `test_collector_panel_js.js` | Integration — state, timeout, empty, duplicate | **P0** |
| `services/db_service.py` | 480 | 35 | 🟡 | `test_db_manager.py`, `test_db_switch_e2e.py` | Integration — transaction, rollback, isolation | **P0** |
| `services/history_service.py` | 580 | 40 | 🔴 | None direct | Integration — filter, aggregate, export, pagination | **P0** |
| `services/layout_service.py` | 160 | 12 | 🔴 | None direct | Integration — layout, resize | **P2** |
| `services/people_service.py` | 200 | 15 | 🔴 | `test_people_undo.py`, `test_search_users.py` | Integration — filter, merge, undo | **P1** |
| `services/cdp_service.py` | 120 | 10 | 🔴 | `test_cdp_events.py` (indirect) | Integration — event, disconnect | **P2** |
| `services/undo_service.py` | 500 | 35 | 🔴 | `test_merge_undo_enabled.py`, `test_undo_service` missing | Integration — command, redo, failure | **P1** |

---

## F. `stores/` — Persistence

| Module | Lines | Functions | Status | Existing Tests | Design Target | Priority |
|---|---|---|---|---|---|---|
| `stores/history_repo.py` | 470 | 30 | 🟡 | `test_history_repo.py` | Integration — CRUD, query, version conflict | **P1** |
| `stores/history_db.py` | 560 | 40 | 🟡 | `test_db_migration.py`, `test_db_unified_world.py` | Integration — schema, query, migration rollback | **P1** |
| `stores/history_models.py` | 230 | 12 | 🟡 | `test_db_schema_migration.py` | Unit — validation, field types | **P2** |
| `stores/media_store.py` | 400 | 30 | 🟡 | `test_media_store.py`, `test_media_recovery_e2e.py` | Integration — path, duplicate, limit, recovery | **P1** |
| `stores/label_store.py` | 560 | 40 | 🟡 | `test_label_store.py`, `test_person_labels.py` | Integration — hierarchy, orphan, import/export | **P1** |
| `stores/block_store.py` | 110 | 8 | 🔴 | None | Unit — block, persist | **P2** |
| `stores/bookmark_store.py` | 50 | 5 | 🔴 | None | Unit — bookmark, list | **P2** |
| `stores/preset_store.py` | 140 | 10 | 🔴 | None | Unit — preset, default | **P2** |
| `stores/session_store.py` | 70 | 6 | 🔴 | None | Unit — session, expire | **P2** |
| `stores/settings_store.py` | 120 | 10 | 🔴 | None | Unit — settings, merge | **P2** |
| `stores/undo_store.py` | 80 | 6 | 🔴 | `test_merge_undo_enabled.py` | Unit — undo state, persist | **P2** |
| `stores/user_memory.py` | 170 | 12 | 🔴 | `test_click_user_memory.py` | Unit — memory, link, cycle | **P2** |
| `stores/jsonio.py` | 110 | 8 | 🔴 | None | Unit — load/save, corrupt | **P2** |
| `stores/migration.py` | 80 | 6 | 🔴 | `test_db_migration.py` | Integration — migrate, rollback | **P2** |

---

## G. `main.py` — Entry

| Module | Lines | Functions | Status | Existing Tests | Design Target | Priority |
|---|---|---|---|---|---|---|
| `main.py` | 680 | 30 | 🔴 | None direct | Smoke — start, registry scan, DB init, exit | **P0** |

---

## H. JS / Wire Tests (`tests/*.js`)

| File / Area | Lines | Status | Existing Tests | Design Target | Priority |
|---|---|---|---|---|---|
| `tests/test_bridge_router.js` | 100 | 🟡 | Exists | Contract assertions for all routes | **P1** |
| `tests/test_sash_core.js` / `test_sash_core_v2.js` | 200 | 🟡 | Exists | Core sash logic, resize, control | **P1** |
| `tests/test_history_agent_js.js` | 300 | 🟡 | Exists | Agent format, event names | **P1** |
| `tests/test_grid_persistence.js` / `test_grid_close_autosave.js` | 250 | 🟡 | Exists | Grid state, close, autosave | **P1** |
| `tests/test_labels_ui_js.js` / `test_label_badge_...` | 200 | 🟡 | Exists | Label badge, edit, delete | **P2** |
| `tests/test_js_core.js` | 150 | 🟡 | Exists | Core JS contracts | **P2** |
| `tests/dom_stub.js` / `tests/js_harness.js` | 300 | 🟢 | Exists | Harness / stub — maintain | **P2** |

---

## Summary Table — Coverage Gap by Priority

| Priority | Count of Modules | Action Required |
|---|---|---|
| **P0** (Critical — cover before any refactor) | ~15 | Write full unit + integration; set CI gate |
| **P1** (High — expand existing) | ~20 | Add edge cases, regression, mutation sample |
| **P2** (Medium — maintain / fill gaps) | ~20 | Basic unit tests, smoke, contract assertions |

**Total modules requiring action:** ~55 source modules + 35 JS test files.  
**Estimated new test LOC needed:** 3,000–5,000 (to reach ~1:1 ratio with source).  
**Estimated time with team:** 10–12 working days (Phase 3–5, per Roadmap).

---

*Matrix completed: 2026-09-09*  
*Next step: Phase 3 — Execute starter (`tests/test_core_logic_coverage.py`) and begin `core/` P0 tests.*
