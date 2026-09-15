# Round I — Updated Metrics With Last Fixes — 2026-09-15

**Branch:** `arena/01a0a172-chat-v-bot` @ `e34bc8c` (after 3 hotfixes)
**Previous plan:** `ROUND_I_REBALANCED_2026-09-15.md` @ `d4f71af`
**Last changes included:**
- `62e85de` Fix `_as_record` missing from `history_repo_identity` facade
- `edc53b0` Fix `clean_blocks`, `schedule` missing from `stack_bridge_parts` facade
- `e34bc8c` Fix export preset: add `WindowPresetBridge` to `BRIDGE_CLASSES` (was missing since `3d7f799`), add Blob download fallback in `window-presets-actions.js` (112→135 LOC)

---

## 1. New Metrics Snapshot (2026-09-15 13:02 UTC, after hotfixes)

### 1.1 Python — Complexity still CLOSED

| Check | Value | Verdict |
|---|---|---|
| CC>10 | 0 / 2457 blocks | ✅ PASS |
| Cognitive>15 | 0 | ✅ PASS |
| Nesting>4 | 0 | ✅ PASS |
| Functions >30 LOC | ~30 (backend 10, bridge 6, services 15, stores 19, actions 9) | tail |
| Classes >150 LOC | **27** (was 36 at c5ff8f2) | ↓9 — improvement from H-C5 splits |
| Files >500 LOC | **3** (dom_highlight 514, router 487, media_handler 474) | was 4 |
| Files >300 LOC | **3** | was 23 at 2026-09-14 baseline |
| Line coverage | 93.16% | +0.5 vs 92.64% baseline |
| Branch coverage | 88.85% | +0.8 vs 88.03% |
| rule16_gate | PASS | ratchet intact |
| quick_validate | PASS | double_audit, smell, file_floor, rule16 |

**File coverage floor (9 below 80%):**
```
67.3% bridge/layout_bridge.py (97 stmts)
70.1% services/db_deletion_flow_remove.py (114)
70.5% services/db_registry.py (164)
72.1% bridge/collector_bridge.py (115)
73.5% services/db_deletion_scan.py (117)
76.1% bridge/people_bridge.py (101)
77.7% stores/media_fetch.py (182)
78.0% bridge/label_bridge.py (102)
78.8% services/db_deletion_flow_detach.py (52)
```
No ratchet regression. Stale: `media_fetch_http.py` gone.

**Smell inventory:**
- Vulture 7 (unchanged)
- Clones 13 groups / 96 lines (import headers only)
- Wide params 11: mostly RULE 3 block settings, 2 real: `router.__init__` 8 params, `chat_sync.run_sync` 5 params

**Classes >150 LOC (27):**
```
249 services/db_lifecycle.py DbLifecycle
237 stores/history_repo_append.py AppendPlanner
232 stores/history_db.py HistoryDB
225 stores/history_repo.py HistoryRepo
225 actions/click_user.py ClickUser
222 stores/label_store.py LabelStore
216 services/collector_service.py Collector
214 stores/media_store.py MediaStore
206 stores/history_repo_media.py MediaRecovery
202 stores/user_memory.py UserMemory
197 actions/scroll_parse_run.py ScrollRunPart
194 services/db_registry.py DbRegistry
193 stores/history_schema_repair.py SchemaMigrator
192 services/people_service.py PeopleService
182 services/undo_service.py UndoService
182 services/run/coordinator.py RunCoordinator
180 bridge/history_bridge.py HistoryBridge
179 backend/history_query.py HistoryQuery
178 backend/chat_sync_session.py SyncSession
178 actions/collect_history.py _CollectRun
176 bridge/layout_bridge.py LayoutBridge
165 bridge/undo_bridge.py UndoBridge
163 stores/preset_store.py PresetStore
163 services/run/error_recovery.py RunExecutionMixin
155 stores/history_schema_legacy.py LegacyRebuild
153 services/undo_support.py UndoProjection
151 bridge/collector_bridge.py CollectorBridge
```

### 1.2 JavaScript — Still Open Flank

| Metric | Now | Baseline 2026-09-14 | Delta |
|---|---|---:|---|
| Total files | 85 / 11,182 LOC | 42 / 12,229 | -1,047 LOC, +43 files (split) |
| Files >500 | 2 (`chat_agent 803`, `sash-core 684`) | 1 (sash-grid 1,361) | -1 god, but still 2 |
| Files >300 | 5 (`sash-core 684`, `sash-grid-windows 487`, `history-model 412`, `history-view 345`, `collector-panel 303`) | ~5 | same |
| Functions >30 | 37 | 49 | -12 |
| Largest object | `collector-panel 290/15`, `app-bridge 270/15`, `stack-dnd-menu 242/16` | SashGrid 1,331/69 | -1,041 LOC |
| JS coverage | 69.49% (5365/7721) | 82.52% | -13% regression |
| Never-loaded | ~40 files | 6 | +34 (new split files not loaded by Node tests) |
| Node failures | 14 | 0 | +14 |

**js_gate: 86 violations (unchanged after hotfixes, but now router 487 not counted in JS)**
- size 14: `bot-settings-core 21 methods>15`, 7 NEW funcs >30 (`history-db-core init 45`, `history-db-render render 34`, `history-store-core init 45`, `labels-assign renderAssign 50`, `labels-edit _editRow 54`, `labels-filter renderFilter 45`, `labels-render pill 47`, `sash-core anon 619→661`, `moveWindow 43→51`, `sash-core 684>642`, `drag-core 194>150`, `drag-spec 159>150`, `_specGeometry 36>30`, `user-table-core init 37`)
- coverage 72: 15 baseline drops (`bot-chat 0<97.5`, `bot-connection-view 41.6<99.6`, `collector-panel 70<95.4`, `sash-grid-windows 23.4<68.2`, `sash-grid 0<99.1`, etc.) + 40 NEW never-loaded + total 69.49<82.52 + 14 Node failures

**Window preset export fix:**
- `bridge/router.py` 486→487 LOC (added WindowPresetBridge), now 14 bridges
- `ui/js/window-presets-actions.js` 112→135 LOC (added `_exportViaDownload` Blob fallback), still ideal ≤150, `js_size` 136 LOC / 23 funcs / 126 obj / 12 methods
- Before: `export_window_preset` slot missing → JS `App.bridge.export_window_preset` undefined → error `"Export requires the desktop bridge to choose a folder."`
- After: slot present, plus Blob fallback works even without bridge (browser testing)

### 1.3 Hotfix Impact on Metrics

| Fix | File LOC Δ | Class LOC Δ | Gate |
|---|---|---|---|
| `_as_record` export | `history_repo_identity.py` 24→26 (+2) | — | fixes ImportError chain |
| `clean_blocks`, `schedule` export | `stack_bridge_parts.py` 31→32 (+1) | — | fixes ImportError chain |
| `WindowPresetBridge` in router + Blob fallback | `router.py` 486→487 (+1), `window-presets-actions.js` 112→135 (+23) | router class still ≤150 facade, JS still ≤150 ideal | fixes export bug, restores functionality |

No RULE 16 violation, no new clone, no coverage drop.

---

## 2. Updated Prioritized Problems (Including Last Changes)

### P0 — JS God Objects & Coverage Collapse (still P0)
- **Where:** `sash-core 684`, `sash-grid-windows 487`, `history-model 412`, `history-view 345`, `collector-panel 303`, `bot-settings-core 21 methods`, `app-bridge 284` (270/15), `stack-dnd-form 283` (222/13), `stack-dnd-render 281`, `stack-dnd-menu 245` (242/16)
- **Why:** 5 files >300, 37 funcs >30, 86 gate violations, coverage 69% (was 82%), 40 never-loaded, 14 Node failures
- **Effort:** ~3,200 LOC god to split, + coverage restore, + Node test fix

### P1 — Bridge Layer + Router (now includes WindowPreset fix)
- **Where:** `router 487` (was 486, now 14 bridges, still god), `history_bridge 180`, `layout_bridge 176` (get_app_state 40, 67.3% cov), `undo_bridge 165`, `collector_bridge 151` (72.1% cov), `window_preset_bridge` 98 (newly registered, but its crud/export parts 97+75+50 already split, MI 53/58/72 — OK), `people_bridge 101` (76.1%), `label_bridge 102` (78.0%)
- **Why:** Router high Ce (imports 14 bridges), wide params `__init__` 8, 3 files below 80%, WindowPresetBridge was missing since audit — now fixed but needs tests for export path
- **Effort:** ~1,200 LOC god + coverage lift 3 files to 80%

### P2 — Services DB & Collector (largest Python god)
- **Where:** `db_lifecycle 288` (249 class, _clean_unlocked 42), `db_registry 265` (194 class, info 32, 70.5% cov), `collector_service 257` (216 class), `db_deletion_flow 202`, `db_deletion_scan 216` (73.5%), `db_deletion_policy 219`, `db_media_scan 232`, `world_lock 285`, `media_store 278` (214 class), `dom_highlight 514`, `media_handler 474`, `chat_parser 426`, `bot_chat 299`
- **Why:** 8 classes >150, 2 files >400, 3 files below 80%, MI low
- **Effort:** ~2,000 LOC god + coverage

### P3 — Stores History & People/Labels (data access monoliths)
- **Where:** `history_repo_append 267` (237 class, append 46, _write 41, _prepend 41), `history_db 300` (232 class, init 54), `history_repo 277` (225 class), `label_store 287` (222 class), `user_memory 284` (202 class), `history_repo_media 263` (206 class, recover_media 36), `history_schema_repair 229` (193 class), `preset_store 227` (163 class), `people_service 227` (192 class), `undo_service 227` (182), `run/coordinator 216` (182)
- **Why:** 10 classes >150, many funcs >30, stores_modules family count 15 must stay
- **Effort:** ~2,100 LOC god

**Total god LOC:** P0 ~3,200 + P1 ~1,200 + P2 ~2,000 + P3 ~2,100 = **~8,500** (was 12,280 before H-C5, now down). Balanced into 4 areas ~2,100–2,200 god each.

---

## 3. Rebalanced Areas — Equal Time Difficulty (2.5 days each) — Updated

### Area A — Grid & Layout + Router + Undo (Fixed Export Included)

**Domain:** Grid, layout persistence, undo, router dispatch, window presets. Vocabulary: `SashCore`, `LayoutService`, `UndoService`, `Router`, `WindowPresetBridge`.

**Files (god 3,086 → 3,087 after fix):**
- JS: `sash-core 684`, `sash-grid-windows 487`, `sash-grid-tree 243`, `sash-grid-presets 159`, `drag-core 200`, `drag-spec 165`, `drag-resize 133`, `sash-grid 110`, `app-bridge 284`, `window-presets-actions 135` (now has Blob fallback), `window-presets-core 111`, `window-presets-preview 82`
- Python: `router 487` (now 14 bridges, includes WindowPresetBridge), `layout_bridge 196` (176 class, get_app_state 40, 67.3%), `undo_bridge 186` (165), `window_preset_bridge 98` (facade, already split into crud 97+export 50+...), `window_preset_crud 97`, `window_preset_export 51`, `undo_service 227` (182), `undo_support 292` (153), `undo_apply 259`, `undo_archive 235`

**God sum:** 684+487+243+284+487+196+186+227+292 = **3,086** (balanced)

**Last changes impact:** Router now correctly exposes `export_window_preset`, `show_window_preset_in_folder`, `list_window_presets`, `save_window_preset`, `load_window_preset`, `delete_window_preset`. JS export now works via bridge + Blob fallback. No extra effort, but Area A acceptance must include export works.

**Steps:**
1. A1 — Sash-Core + Router: split sash-core 684→tree/ops/validate (moveWindow 51→3×15), router 487→core/layout/undo/history/collector/people/window_preset (6×~80), options object for `__init__` 8→2, keep WindowPresetBridge registered. Validate js_size + rule16.
2. A2 — Sash-Grid-Windows + Layout/Undo/WindowPreset Bridges: split sash-grid-windows 487→store/ops/menus (221/14→2×110/7), layout_bridge 196→state/persist (get_app_state 40→2×15), undo_bridge 165→core/history, window_preset_bridge already split but add tests for export path (QFileDialog mock). Lift layout_bridge 67.3→80%.
3. A3 — Undo Services + JS Coverage + Export: split undo_service 227→core/apply/archive, undo_support 292→core/schedule/save, fix js_gate objects >150 (drag-core 194, drag-spec 159, app-bridge 270) → extract, NEW funcs >30 (_specGeometry 36) → split, NEW files never loaded → add test_sash_*.js loaders, fix 14 Node failures, verify export via Blob and via bridge (mock QFileDialog). Coverage ≥82.52%.

**Acceptance (updated):**
- No file >300, no class >150, no func >30 NEW, no object >15 methods
- router.__init__ ≤4 params, layout_bridge.get_app_state ≤30
- layout_bridge ≥80%, JS coverage ≥82.52%, 0 never-loaded for these files
- **Export preset works:** with bridge → folder dialog → `window-preset-{name}.json`, without bridge → Blob download → `v1.json`, log `Exported to ...` or `Exported via download`
- quick_validate PASS, js_gate size violations for these files 0

**Time:** 2.5 days

---

### Area B — History System (JS History + Python History Query/Parser + Stores History)

**Domain:** Person history, archive, search, parser. Vocabulary: HistoryBridge, HistoryDB, HistoryRepo, HistoryQuery, ChatParser.

**Files (god 3,227):**
- JS: history-model 412 (386 anon, create 238), history-view 345 (327 anon), history-db-core 106 (init 45), history-db-sort 117, history-db-render 91 (render 34), history-store-core 112 (init 45), history-store-bridge 115, history-store-render 87
- Python: history_query 210 (179 class, page 40, search 50), chat_parser 426, chat_sync_session 297 (178 class), history_db 300 (232 class, init 54), history_repo 277 (225), history_repo_append 267 (237, append 46, _write 41, _prepend 41), history_repo_media 263 (206, recover 36), history_schema 257, history_schema_repair 229 (193), history_schema_legacy 175 (155), history_models 238, history_requests 218, history_bridge 241 (180), history_repo_identity 26 (now exports _as_record, fixed), history_repo_identity_helpers 91 (_as_record, align_batch, resolve_days)

**God sum:** 412+345+210+426+300+277+267+263+257+229+241 = 3,227 (balanced)

**Last changes impact:** `history_repo_identity.py` now exports `_as_record` — fixes ImportError chain `file_bridge_io → preset_io → actions.registry.scan → collect_history → chat_parser → chat_sync_read → history_repo_append`. Area B must ensure facade exports all needed symbols (TAIL_FP_LIMIT, align_batch, resolve_days, _as_record, ConversationIdentity).

**Steps:**
1. B1 — History Query + Parser: split history_query 210→core/search/page/request, chat_parser 426→core/verify/authors, keep CC 0, LOC ≤150
2. B2 — History Stores: split history_db 300 (init 54→_init_tables/_init_indexes), history_repo 277→core/query/mutate, history_repo_append 267→core/write/prepend (append 46→2×15), history_repo_media 263→core/recover (36→2×15), ensure stores_modules 15
3. B3 — History Bridges + JS Model/View + Identity Facade: split history_bridge 180→core/search/delete/append, history-model 412→core/search/render, history-view 345→core/events, fix js_gate NEW funcs (history-db-core init 45→2×15, render 34→2×15, history-store-core init 45→2×15), verify identity facade exports _as_record + align_batch + resolve_days, add Node tests for history panels

**Acceptance:**
- No file >300, no class >150, no func >30
- history_db.init ≤30, history_repo_append.append ≤30
- history-model no anon >300
- Coverage history-model ≥91.3%, history-view ≥93.6%
- stores_modules 15, quick_validate PASS, ImportError chain fixed

**Time:** 2.5 days

---

### Area C — Collector & DB & Media (JS Collector/Stack + Python DB/Media)

**Domain:** Collector, stack DnD, DB lifecycle, media, world lock. Vocabulary: Collector, DbLifecycle, DbRegistry, MediaStore, CollectorBridge.

**Files (god 3,179):**
- JS: collector-panel 303 (290/15, init 59), stack-dnd-form 283 (222/13), stack-dnd-render 281 (157/10), stack-dnd 269 (90/5), stack-dnd-menu 245 (242/16), stack-dnd-history 222, color-picker 229 (211/10, open 73)
- Python: dom_highlight 514 (largest), media_handler 474, db_lifecycle 288 (249 class, _clean_unlocked 42), db_registry 265 (194 class, info 32, 70.5% cov), world_lock 285, media_store 278 (214), collector_service 257 (216), db_media_scan 232, db_deletion_policy 219, db_deletion_scan 216 (73.5%), db_deletion_flow 202, db_deletion_flow_remove 175 (70.1%), db_deletion_flow_detach 52 (78.8%), collector_bridge 171 (151, 72.1%), media_fetch 182 (77.7%)

**God sum:** 303+283+281+269+245+288+265+474+514+257 = 3,179 (balanced)

**Last changes impact:** `stack_bridge_parts.py` now exports `clean_blocks`, `schedule` — fixes ImportError chain `router → stack_bridge → stack_bridge_parts`. Area C must ensure stack_bridge facade exports all needed.

**Steps:**
1. C1 — Media + Dom Highlight + Collector Panel: split dom_highlight 514→core/probe/clear (build_probe is JS literal, allowed 107 but control flow CC≤10, add `ideal-size:` reason), media_handler 474→core/dialog/fetch (_open_dialog 35), collector-panel 303→core/render (290→2×120, init 59→2×25)
2. C2 — DB Lifecycle + Registry + Deletion Flow: split db_lifecycle 249→core/clean/world (_clean 42→2×15), db_registry 194→core/info/scan (info 32→2×15), db_deletion_flow 202→core/remove/detach/policy, lift coverage db_registry 70.5→80%, db_deletion_flow_remove 70.1→80%, db_deletion_scan 73.5→80%, collector_bridge 72.1→80%, media_fetch 77.7→80%
3. C3 — Stack-DnD + Collector Service + Bridge: split stack-dnd-form 283→core/render (222→2×100), stack-dnd-render 281→core/list/config, stack-dnd-menu 245 (242/16→2×120/8), collector_service 216→tick/probe/archive, collector_bridge 151→core/control, fix js_gate collector-panel 290>150, stack-dnd-menu 242>150, color-picker open 73>30, verify stack_bridge_parts exports clean_blocks + schedule

**Acceptance:**
- No file >300, no class >150, no func >30 (except JS literal with ideal-size)
- dom_highlight CC≤10, nesting≤4
- db_registry, db_deletion_flow_remove, collector_bridge, db_deletion_scan, media_fetch ≥80%
- js_size collector-panel ≤300, stack-dnd-menu ≤150 object
- quick_validate PASS, ImportError chain fixed

**Time:** 2.5–3 days (largest files 514+474)

---

### Area D — People & Labels & Bot (JS Labels/User/Bot + Python People/Label/Preset/Bot)

**Domain:** User memory, labels, bot chat, presets. Vocabulary: PeopleService, LabelStore, UserMemory, BotChat, PresetStore.

**Files (god ~3,150):**
- JS: labels 190 (169/9, init 55), labels-assign 145 (132/9, renderAssign 50), labels-model 86, labels-render 106 (pill 47), labels-edit 106 (_editRow 54), labels-filter 88 (renderFilter 45), user-table-core 71 (init 37), user-table-render 86, user-table-actions 77, bot-connection-view 238 (210/17), bot-settings-core 115 (105/21 methods>15), bot-chat-core 86, bot-chat-bridge 70, bot-chat-cards 53, bot-chat-send 66, presets-ui-core 102, presets-ui-stack 89, presets-ui-import 103
- Python: people_service 227 (192), label_store 287 (222), user_memory 284 (202), preset_store 227 (163), bot_chat 299, bot_connections 231, click_user 225 (execute 39), scroll_parse_run 197, collect_history 178, people_bridge 101 (76.1%), label_bridge 102 (78.0%), bot_bridge 185, bot_prompt_bridge 84, bot_settings_bridge 73, preset_io 260

**God sum:** 190+145+238+227+287+284+227+299+231+225 = 2,353 + 800 small = ~3,150 (balanced)

**Last changes impact:** `preset_io` imports `all_action_ids` which triggers `ActionRegistry.scan()` → imports `collect_history` → chain that previously failed due to `_as_record` and `clean_blocks`. Now fixed, but Area D must ensure `actions/__init__.py` scan at import time doesn't cause circular import — consider lazy scan or guard.

**Steps:**
1. D1 — Labels + User Table + People Service: split label_store 287→core/assign/filter (222→3×70), user_memory 284→core/search/persist (202→3×60), people_service 227→core/filter/persist (192→3×60), labels 190→core/render, labels-assign 145→core/render (renderAssign 50→2×20), user-table-core 71 (init 37→2×15), lift people_bridge 76.1→80%, label_bridge 78→80%
2. D2 — Bot Chat + Connections + Bridges: split bot_chat 299→core/chat/connections, bot_connections 231→core/store (130→core/seed/merged), bot-connection-view 238 (210/17→2×100/8), bot-settings-core 115 (105/21→model/render 2×50/10), fix js_gate: bot-settings-core 21 methods>15, labels-assign 50>30, labels-edit 54>30, labels-filter 45>30, labels-render 47>30, user-table-core 37>30, add Node tests for bot files (never-loaded)
3. D3 — Presets + Click User + Collect History + Circular Import Fix: split preset_store 227→core/io (163→2×70), click_user 225→core/execute (39→2×15), collect_history 178→core/run, scroll_parse_run 197→core/options, fix circular import: make `actions/__init__.py` scan lazy (don't scan at import, scan on first `all_action_ids()` call) or make `preset_io` import inside function, lift media_fetch 77.7→80%, fix 14 Node failures

**Acceptance:**
- No file >300, no class >150, no func >30 NEW
- No object >15 methods
- people_bridge, label_bridge, media_fetch ≥80%
- JS bot files coverage restored, bot-chat 0→≥97.5%
- No circular import: `from app.bootstrap import create_container` works without PySide6 mock (with aiosqlite, aiohttp installed)
- quick_validate PASS, js_gate for these files 0 violations

**Time:** 2.5 days

---

## 4. Balanced Summary (After Hotfixes)

| Area | Domain | God LOC | Total LOC | Files >300 | Classes >150 | Funcs >30 | Coverage debt | Est. Days | Last Fix |
|---|---|---:|---:|---:|---:|---:|---|---:|---|
| A Grid & Layout | sash + layout + undo + router + window_preset | 3,086 | 3,861 | 3 (sash-core 684, sash-grid-windows 487, router 487) | 5 (router, layout_bridge, undo_bridge, undo_service, undo_support) | 3 (get_app_state 40, moveWindow 51, _specGeometry 36) | layout_bridge 67.3%, JS sash 23% | 2.5 | WindowPresetBridge added to router, Blob fallback |
| B History | history JS + query/parser + stores history | 3,227 | 3,683 | 3 (history-model 412, history-view 345, chat_parser 426) | 8 (history_query, history_db, history_repo, append, media, schema, bridge) | 6 (init 54, append 46) | history-model 90.8<91.3, history-view 87<93.6 | 2.5 | _as_record export |
| C Collector & DB | collector/stack + db/media | 3,179 | 3,742 | 4 (collector-panel 303, stack-dnd 283/281/269, dom_highlight 514, media_handler 474) | 7 (db_lifecycle 249, db_registry 194, collector 216, world_lock 285, media_store 214) | 5 (_clean 42, _open_dialog 35) | db_registry 70.5%, db_deletion 70-78%, collector_bridge 72% | 2.5–3 | clean_blocks/schedule export |
| D People & Labels & Bot | labels/user/bot + people/label/preset | ~3,150 | ~3,500 | 2 (bot_chat 299, label_store 287, user_memory 284) | 8 (people_service 192, label_store 222, user_memory 202, preset_store 163, click_user 225) | 7 (renderAssign 50, _editRow 54) | people_bridge 76%, label_bridge 78%, media_fetch 77%, bot JS 0% | 2.5 | circular import via preset_io→registry.scan |

**Total:** ~12,642 god LOC, ~14,786 total, 4 areas × ~3,160 god avg → balanced within 10%. Each 2.5 days for Opus 5 / Fable 5.

---

## 5. Branching (Isolated)

- Base: `e34bc8c` (has all hotfixes)
- Branches: `arena/round-i-a-grid`, `b-history`, `c-collector-db`, `d-people-labels-bot`
- Isolation: each touches only its file list, facades keep API, no cross-area imports in same PR, `quick_validate --full --with-clones` + `js_gate` + `js_coverage` before merge
- Merge order: D (stores leaf) → C → B → A, but A can merge first (JS zero Python coupling). For 3 areas: `round-i-a-js`, `round-i-b-bridge`, `round-i-cd-services-stores`

---

## 6. RULE 16/18/19 Gates

Every PR:
- [ ] No new func >30 LOC (except JS literal with `ideal-size: 78 lines reason=single JS payload...`)
- [ ] No new class >150 LOC or >15 methods
- [ ] No new func >4 params
- [ ] CC≤10, cog≤15, nest≤4
- [ ] line ≥93.16%, branch ≥88.85%, no file below 80% (or ratchet update)
- [ ] every new func has test that would fail if deleted (RULE 8)
- [ ] no new vulture, no new clone groups
- [ ] aims at RULE 18 ideal: func 4–20, file 150–300, module 5–15; deviation has `ideal-size:`
- [ ] remediation order RULE 19: nesting→CC→cognitive→size

Commands:
```bash
.venv/bin/python tools/metrics/rule16_gate.py
.venv/bin/python tools/metrics/quick_validate.py --full --with-clones
.venv/bin/python tools/metrics/file_coverage_floor.py
.venv/bin/python tools/metrics/stores_modules.py
.venv/bin/python tools/metrics/js_size.py | sort -k2 -rn | head -n 20
.venv/bin/python tools/metrics/js_gate.py
```

---

## 7. Acceptance for Round I (Updated)

- [ ] Python: 0 files >300, 0 classes >150, 0 funcs >30 (except JS literal), CC>10=0, cog>15=0, nest>4=0
- [ ] JS: 0 files >300 (max 500 hard), 0 objects >15 methods, 0 funcs >30 NEW, coverage ≥82.52%, 0 never-loaded, 0 Node failures
- [ ] Coverage: line ≥93.16%, branch ≥88.85%, no file below 80%
- [ ] Clones: 13 groups / 96 lines, no new groups
- [ ] Stores modules: 15, import graph clean
- [ ] **Export preset works:** with bridge (WindowPresetBridge registered) → folder dialog → `window-preset-{name}.json`, without bridge → Blob download fallback, log success
- [ ] **No ImportError:** `from app.bootstrap import create_container` works, `_as_record`, `clean_blocks`, `schedule` exported, circular import via `actions/__init__.py` scan fixed (lazy)
- [ ] All 4 areas merged, `quick_validate --full --with-clones` PASS, `js_gate` PASS

No code changes in this doc — planning only, updated with hotfixes.
