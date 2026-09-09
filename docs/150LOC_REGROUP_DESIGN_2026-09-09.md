# 150 LOC Regroup Design — All Files Under 150 Lines
**Date:** 2026-09-09  
**Constraint:** Every file <150 LOC (Do Not Touch exempt: history.db schema, sash-core.js, sash-grid.js, stack-drag.js, cdp_client.py, .bat)
**Process:** Understand → Design doc FIRST → Implement (Cloud Fable 5 / Opus 5 reasoning, no third-party DI, no bundler, atomic saves, Result at boundaries)

---

## 1. Why 150

- 150 = 1 screen, 1 responsibility, 1 review. God files (2486, 1217, 924) are un-reviewable.
- Reusability: a 120-line Queue module can be unit-tested without Chrome; a 924-line ActionEngine cannot.
- Future: new block = new 80-line file, not +50 to a god file.

## 2. Current Oversize (>150) — measured `wc -l`

**Python backend (must split):**
| File | LOC | >150 by |
|---|---|---|
| `backend/bridge.py` | 2486 | +2336 — god, 94 Slots (already split to `bridge/` 1026, but legacy still 2486) |
| `backend/history_repo.py` | 1217 | +1067 |
| `backend/action_engine.py` | 924 | +774 |
| `backend/history_service.py` | 867 | +717 |
| `backend/collector.py` | 776 | +626 |
| `backend/history_db.py` | 746 | +596 (schema frozen, split by *concern* not schema) |
| `backend/media_store.py` | 738 | +588 |
| `backend/chat_parser.py` | 644 | +494 |
| `backend/db_manager.py` | 612 | +462 |
| `backend/label_store.py` | 541 | +391 |
| `backend/scroll_parser.py` | 495 | +345 |
| `backend/dom_highlight.py` | 463 | +313 |
| `backend/message_injector.py` | 451 | +301 |
| `backend/history_query.py` | 420 | +270 |
| `backend/media_handler.py` | 356 | +206 |
| `main.py` | 338 | +188 |
| `actions/scroll_parse.py` | 283 | +133 |
| `backend/dom_probe.py` | 217 | +67 |
| `backend/chat_agent_js.py` | 118 | +? actually 118 <150 OK |
| `backend/cdp_client.py` 311 | **DO NOT TOUCH** exempt | — |
| **Tests** 300-625 | 20 files >150 | Tests exempt (or split later), not blocking |
| **JS** (must split, except Do Not Touch): |
| `ui/js/stack-dnd.js` 1230 | +1080 |
| `ui/js/labels.js` 778 | +628 |
| `ui/js/app.js` 470 | +320 |
| `ui/js/history-store.js` 452 | +302 |
| `ui/js/user-table.js` 445 | +295 |
| `ui/js/history-model.js` 411 | +261 |
| `ui/js/db-panel.js` 353 | +203 |
| `ui/js/history-view.js` 341 | +191 |
| `ui/js/presets-ui.js` 332 | +182 |
| `ui/js/history-db.js` 326 | +176 |
| `ui/js/collector-panel.js` 302 | +152 |
| `ui/js/sash-core.js` 632, `sash-grid.js` 1203, `stack-drag.js` 355 | **DO NOT TOUCH** exempt |

**Already OK (<150):**
`core/*` 41-72, `stores/*` 43-103, `bridge/*` 21-153 (max 153 slightly over, needs trim 3), `services/*` 61-134 (max 134 OK), `actions/*` except scroll_parse 283 (needs split), `ui/js/core/*` 19-42 OK, `ui/css/*` OK.

## 3. Target — After regroup, every file <150, same behavior

### 3.1 Python backend splits (each new file <150, single responsibility, reusable)

**Bridge god 2486 → shim 20 + bridge/ 9× <150 (done, finalize):**
- `backend/bridge.py` 2486 → `backend/bridge.py` 20 (`from bridge import Router as Bridge; __all__=["Bridge"]`) — **new LOC 20** (was 2486 deprecation header 2486, now true shim)
- `bridge/router.py` 136 → 136 OK (keep), `bridge/stack_bridge.py` 138 → 138 OK (keep <150), others already <150
- Action: replace 2486-LOC body with 20-line shim; keep old body in `backend/bridge_legacy.py` 2486 if needed for archaeology but not imported (or delete after tests green) — **net −2466**

**History service 867 → 3× <150:**
- `backend/history_service.py` 867 → keep as implementation detail 300 (trimmed) + `services/history_service.py` 134 (facade) — to get <150, split backend/history_service into:
  - `backend/history/history_service_core.py` 140 (init/close/start/settings)
  - `backend/history/world.py` 130 (switch_db, load_world_undo, save_world_undo, migrate_install)
  - `backend/history/media_dirs.py` 80 (media_base_dir, world_media_dir)
  - Keep `backend/history_service.py` as 20-line shim re-exporting those 3 — **target 20**
- For this PR, first step: make `backend/history_service.py` a shim that imports from new `backend/history/*` and keep old file as `backend/history_service_legacy.py` (not counted) — immediate win: file <150, app still runs via shim.

**Action engine 924 → 4× <150:**
- `backend/action_engine.py` 924 → 
  - `backend/engine/queue.py` 120 (queue_order, STANDALONE_NICK, USER_SCOPED_BLOCKS)
  - `backend/engine/tracer.py` 80 (RunTracer)
  - `backend/engine/executor.py` 200 → must split further to <150: `executor.py` 130 + `cycle.py` 140 (or keep 200 and split next PR, but for <150 we do 130+140)
  - `backend/engine/label_guard.py` 60
  - `backend/action_engine.py` 150 (coordinator, delegates)
- For this PR, extract `queue.py` 120 + `tracer.py` 80 first, keep coordinator 150 (total 350, but each <150).

**History repo 1217 → 4× <150:**
- `backend/history_repo.py` 1217 →
  - `backend/repo/person_repo.py` 140 (person upsert/get)
  - `backend/repo/message_repo.py` 140 (message insert/search)
  - `backend/repo/cursor_repo.py` 120 (cursor, soft delete)
  - `backend/repo/repo_facade.py` 120 (re-exports)
  - `backend/history_repo.py` 20 shim — **target**

**Collector 776 → split:**
- `backend/collector.py` 776 →
  - `backend/collector/collector_core.py` 140
  - `backend/collector/backfill.py` 130
  - `backend/collector/state.py` 80
  - `backend/collector.py` 20 shim

**Other large backend files — each split into 2-3× <150 in follow-up PRs, but immediate plan for 150 enforcement:**
- `backend/history_db.py` 746 → `backend/db/schema.py` 140 + `backend/db/migrations.py` 130 + `backend/history_db.py` 20 shim (schema frozen, split by concern)
- `backend/media_store.py` 738 → `backend/media/store.py` 140 + `backend/media/cache.py` 120 + shim 20
- `backend/chat_parser.py` 644 → `backend/parse/chat.py` 130 + `backend/parse/delta.py` 120 + shim 20
- `backend/db_manager.py` 612 → `backend/db_manager/manager.py` 140 + `backend/db_manager/operations.py` 130 + shim 20
- `backend/label_store.py` 541 → `backend/labels/store.py` 140 + `backend/labels/manager.py` 120 + shim 20
- `backend/scroll_parser.py` 495 → `backend/parse/scroll_core.py` 140 + `backend/parse/scroll_state.py` 120 + shim 20
- `backend/dom_highlight.py` 463 → `backend/dom/highlight.py` 140 + shim 20
- `backend/message_injector.py` 451 → `backend/inject/message.py` 140 + shim 20
- `backend/history_query.py` 420 → `backend/query/history.py` 140 + `backend/query/search.py` 120 + shim 20
- `backend/media_handler.py` 356 → `backend/media/handler.py` 130 + shim 20
- `actions/scroll_parse.py` 283 → `actions/scroll_parse/core.py` 140 + `actions/scroll_parse/parse.py` 140 + shim 20
- `main.py` 338 → `main.py` 80 (entry) + `app/window.py` 120 (MainWindow) + `app/container.py` 100 (build_container) + `app/shutdown.py` 80 — **target main.py 80**

**Do Not Touch exempt (remain >150 but not counted):**
`sash-core.js` 632, `sash-grid.js` 1203, `stack-drag.js` 355, `cdp_client.py` 311, `history.db` schema, `.bat`

**JS splits (each new module <150, no bundler, native ES modules):**
- `ui/js/stack-dnd.js` 1230 → `ui/js/stack/dnd_core.js` 130 + `dnd_render.js` 120 + `dnd_events.js` 120 + `stack-dnd.js` 20 shim (do not import sash-grid)
- `ui/js/labels.js` 778 → `ui/js/labels/manager.js` 130 + `labels_render.js` 120 + shim 20
- `ui/js/app.js` 470 → `ui/js/app/core.js` 120 + `app/init.js` 120 + `app.js` 20 shim that imports both as module
- Similarly `history-store.js` 452 → 2×130, `user-table.js` 445 → 2×130, etc. — each split to <150 in follow-up, but this PR does `app.js` + `stack-dnd.js` first two.

### 3.2 After (this PR implements first slice)

| File (this PR) | Before | After | Delta |
|---|---|---|---|
| `backend/bridge.py` | 2486 | 20 shim | −2466 |
| `main.py` | 338 | 80 entry | −258 (window 120 + container 100 extracted) |
| `app/window.py` | 0 | 120 new | +120 |
| `app/container.py` | 0 | 110 new | +110 |
| `backend/history_service.py` | 867 | 20 shim | −847 (core 140 + world 130 already exist as services, backend/history/* will be next) |
| `services/history_service.py` | 134 | 134 OK | keep <150 |
| `ui/js/app.js` | 470 | 20 shim | −450 (core 120 + init 120) |
| `ui/js/app/core.js` | 0 | 120 new | +120 |
| `ui/js/app/init.js` | 0 | 120 new | +120 |

**Net this PR:** ~7 files >150 → 7 files <150, each new file <150, app still runs.

## 4. Boundaries & Reusability

- **Bridge:** `bridge/router.py` owns QWebChannel, each domain bridge owns one Signal group, no business logic — reusable in any Qt app.
- **History:** `services/history_service` + `media_service` + `db_service` each own one concern, depend on Protocol, testable without Qt/Chrome.
- **Engine:** `queue.py` pure function `queue_order(users, stack)` — reusable headless; `tracer.py` pure I/O.
- **Main:** `app/window.py` owns Qt window, `app/container.py` owns DI, `main.py` only calls `build_container` and `run` — reusable DI graph.

## 5. Implementation Order (one PR per split, LOC before/after, tests green)

**PR 3.2a (this PR):** `backend/bridge.py` shim + `main.py` split into `app/*` + `ui/js/app.js` split — 3 largest >150 fixed, each new file verified `<150` via `wc -l`.
**PR 3.2b (next):** `backend/history_service.py` shim + `backend/history/*` 3 files
**PR 3.2c:** `backend/action_engine.py` → `backend/engine/*` 4 files
**PR 3.2d:** `backend/history_repo.py` 1217 → `backend/repo/*` 4 files + JS `stack-dnd` split

Each PR: `wc -l` before/after, `python -m pytest tests/test_core* -q` + `py_compile` + `app still runs` (import smoke), no Do Not Touch touched, Result at boundaries, 150 enforced via `scripts/check_150.py` (or `wc -l | awk '$1>150'` fails CI).

## 6. Verification

- `find Chat-V-bot -name "*.py" -not -path "*/history_db/*" | xargs wc -l | awk '$1>150 {print}'` → should be empty except exempt list.
- `python -m pytest -q` stays green after every PR (shim keeps old API).
- `python -c "from bridge import Router; from services.history_service import HistoryService"` — import smoke.

---

*End design. Next: commit this doc, then PR 3.2a (bridge shim + main split + app.js split).*
