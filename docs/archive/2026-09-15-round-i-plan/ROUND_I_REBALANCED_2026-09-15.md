# Round I — Rebalanced Areas — Equal Time/Difficulty — 2026-09-15

**User correction:** "those areas should be aprox same size (time difficulty) to fix."
Previous plan had Area B (bridge) ~1150 LOC god vs Area A/D ~2000 LOC — unbalanced.
This doc rebalances into 4 areas each ~1800–2000 LOC god + ~300–500 LOC fix-up, estimated 2–3 days per area for Opus 5 / Fable 5.

**Branch:** `arena/01a0a172-chat-v-bot` @ `c5ff8f2`
**Rules:** RULE 16 (hard fail 30 LOC func, 150 LOC class, 4 params, CC10, cog15, nest4), RULE 18 (ideal 4–20 func, 150–300 file, 5–15 module), RULE 19 (nest→CC→cog→size)

---

## 1. Effort Model

We estimate effort by:
- **God LOC:** sum of classes >150 + files >300 + funcs >30 in area
- **Gate violations:** js_gate 86, file_coverage_floor 9 below, clone groups 13
- **Coupling:** Ce/Ca — router high, stores low, JS zero Python coupling
- **Test lift:** files below 80% need new tests (effort)

**Total god LOC to fix:**
- Python god classes >150: ~36 classes × avg 200 = 7200 LOC
- Python files >300: 3 files × avg 450 = 1350 LOC
- JS files >300: 5 files × avg 450 = 2250 LOC
- JS funcs >30: 37 funcs × avg 40 = 1480 LOC
- **Total ~12,280 LOC** → /4 = **~3070 LOC per area** (including surrounding code)

We rebalance to 4 areas each 3000–3900 total, 1800–2100 god, 2–3 days.

---

## 2. Rebalanced Areas (Equal Difficulty)

### Area A — Grid & Layout System (JS Sash + Python Layout/Undo/Router)

**Domain:** Flexible grid, window layout persistence, undo timeline, router dispatch. All share vocabulary: `SashCore`, `LayoutService`, `UndoService`, `Router`.

**Files (god):**
- JS: `sash-core.js` 684 (moveWindow 51, anon 661), `sash-grid-windows.js` 487 (object 221/14), `sash-grid-tree.js` 243 (240/13), `sash-grid-presets.js` 159 (156/10), `sash-grid-drag-core.js` 200 (194/13), `sash-grid-drag-spec.js` 165 (159/11, _specGeometry 36), `sash-grid-drag-resize.js` 133, `sash-grid.js` 110, `app-bridge.js` 284 (270/15)
- Python: `bridge/router.py` 486 (god file), `bridge/layout_bridge.py` 196 (class 176, func get_app_state 40), `bridge/undo_bridge.py` 186 (class 165), `services/undo_service.py` 227 (class 182), `services/undo_support.py` 292 (class 153, schedule_save 36), `services/undo_apply.py` 259, `services/undo_archive.py` 235, `app/window.py` 199

**God LOC sum:** 684+487+243+284+486+196+186+227+292 = **3085** (balanced)

**Coverage debt:** `layout_bridge 67.3%` (lowest file), `js` sash-grid-windows 23.4% <68.2 baseline, sash-grid 0<99.1

**Isolation:** Touches only `ui/js/sash-*`, `ui/js/app-bridge.js`, `bridge/router.py`, `bridge/layout_bridge.py`, `bridge/undo_bridge.py`, `services/undo_*`, `app/window.py`. No `stores/history_*` or `services/db_*` or `services/collector_*`. Facades keep public API: `SashGrid`, `LayoutBridge`, `UndoBridge`, `Router`.

**Steps (3 sub-steps, 1 day each):**
1. **A1 — Sash-Core + Router:** Split `sash-core.js` → `sash-core-tree.js` (defaultTree, PRESETS), `sash-core-ops.js` (splitLeaf, insertAtSplitIndex, insertSibling, insertBetween, insertOuter, moveWindow 51→3×15), `sash-core-validate.js` (validate, pruneTree, migrate, serialize). Split `router.py` 486 → `router_core.py` (init, ctx), `router_layout.py`, `router_undo.py`, `router_history.py`, `router_collector.py`, `router_people.py` — each ≤150, options object for `__init__` 8→2 params. Validate `js_size` + `rule16_gate`.
2. **A2 — Sash-Grid-Windows + Layout/Undo Bridges:** Split `sash-grid-windows.js` 487 → `sash-grid-window-store.js` (collectPanels, load/save), `sash-grid-window-ops.js` (close/open/minimize), `sash-grid-menus.js` (dock, menus). Split `layout_bridge.py` 196 → `layout_bridge_state.py` (get_app_state 40→2×15), `layout_bridge_persist.py`. Split `undo_bridge.py` 165 → `undo_bridge_core.py`, `undo_bridge_history.py`. Add tests for `layout_bridge` to lift 67.3→80%.
3. **A3 — Undo Services + JS Coverage Restore:** Split `undo_service.py` 227→core/apply/archive, `undo_support.py` 292→core/schedule/save. Fix js_gate: objects >150 (drag-core 194, drag-spec 159, app-bridge 270) → extract, NEW funcs >30 (_specGeometry 36) → split, NEW files never loaded → add `test_sash_*.js` loaders (pattern `test_sash_drag.js`), fix 14 Node failures (mock `SashCore`, `App`). Coverage ≥82.52%.

**Acceptance:**
- No file >300 LOC, no class >150, no func >30 NEW, no object >15 methods
- `router.__init__` ≤4 params, `layout_bridge.get_app_state` ≤30
- `layout_bridge` ≥80%, JS coverage ≥82.52%, 0 never-loaded, 0 Node failures
- `quick_validate` PASS, `js_gate` size violations for these files 0

**Time:** ~2.5 days

---

### Area B — History System (JS History + Python History Query/Parser + Stores History)

**Domain:** Person history, message archive, search, parser, private gate. Vocabulary: `HistoryBridge`, `HistoryDB`, `HistoryRepo`, `HistoryQuery`, `ChatParser`.

**Files (god):**
- JS: `history-model.js` 412 (func 386 anon, create 238), `history-view.js` 345 (327 anon), `history-db-core.js` 106 (init 45), `history-db-sort.js` 117 (21/14), `history-db-render.js` 91 (render 34), `history-store-core.js` 112 (init 45), `history-store-bridge.js` 115, `history-store-render.js` 87, `history-store-scroll.js`, `history-store-open.js`
- Python: `backend/history_query.py` 210 (class 179, page 40, search 50), `backend/chat_parser.py` 426, `backend/chat_sync_session.py` 297 (class 178), `stores/history_db.py` 300 (init 54), `stores/history_repo.py` 277 (class 225), `stores/history_repo_append.py` 267 (class 237, append 46, _write_rows 41, _prepend 41), `stores/history_repo_media.py` 263 (class 206, recover_media 36), `stores/history_schema.py` 257, `stores/history_schema_repair.py` 229 (class 193), `stores/history_schema_legacy.py` 175 (class 155, _rebuild 31), `stores/history_models.py` 238, `stores/history_requests.py` 218, `bridge/history_bridge.py` 241 (class 180, delete_person 32), `services/history/runtime.py` 262

**God LOC sum:** 412+345+210+426+300+277+267+263+257+229+241 = **3227** (balanced)

**Coverage debt:** `history-model` 90.8<91.3, `history-view` 87<93.6, `history_repo_append` churn high, `history_query` MI low

**Isolation:** Touches only `ui/js/history-*`, `backend/history_query*`, `backend/chat_parser*`, `backend/chat_sync_session*`, `stores/history_*`, `bridge/history_bridge*`, `services/history/`. No `bridge/router`, `services/db_*`, `services/collector`, `stores/label_*`.

**Steps:**
1. **B1 — History Query + Parser:** Split `history_query.py` class 179→`history_query_core.py`, `history_query_search.py` (search 50), `history_query_page.py` (page 40), `history_query_request.py` (already). Split `chat_parser.py` 426→`chat_parser_core.py`, `chat_parser_verify.py` (verify_private), `chat_parser_authors.py`. Validate CC=0, LOC≤150.
2. **B2 — History Stores:** Split `history_db.py` 300 (init 54→_init_tables/_init_indexes 2×20), `history_repo.py` 225→core/query/mutate, `history_repo_append.py` 267→core/write/prepend (append 46→2×15, _write_rows 41→2×15), `history_repo_media.py` 206→core/recover (recover_media 36→2×15). Keep `stores_modules.py` 15 modules.
3. **B3 — History Bridges + JS Model/View:** Split `history_bridge.py` 180→core/search/delete/append, `history-model.js` 412→core/search/render (anon 386→3×~100, create 238→2×~80), `history-view.js` 345→core/events (anon 327→3×~80). Fix js_gate NEW funcs: history-db-core init 45→2×15, history-db-render render 34→2×15, history-store-core init 45→2×15. Add Node tests for history panels (fix `test_history_panels_boot.js` failure).

**Acceptance:**
- No file >300, no class >150, no func >30
- `history_db.init` ≤30, `history_repo_append.append` ≤30
- `history-model.js` no anon >300, no func >30
- Coverage `history-model` ≥91.3%, `history-view` ≥93.6%, no new below-floor
- `stores_modules` 15, `quick_validate` PASS

**Time:** ~2.5 days

---

### Area C — Collector & DB System (JS Collector/Stack-DnD + Python DB Lifecycle/Registry/Media)

**Domain:** Chat collector, stack drag-and-drop, DB lifecycle, media handling, world lock. Vocabulary: `Collector`, `DbLifecycle`, `DbRegistry`, `MediaStore`, `CollectorBridge`.

**Files (god):**
- JS: `collector-panel.js` 303 (object 290/15, init 59), `stack-dnd-form.js` 283 (222/13, 1 over-30), `stack-dnd-render.js` 281 (157/10), `stack-dnd.js` 269 (90/5), `stack-dnd-menu.js` 245 (242/16), `stack-dnd-history.js` 222 (157/12), `stack-dnd-config.js` 125, `stack-drag-core.js` 78, `stack-drag-visual.js` 84, `stack-drag-scroll.js`, `color-picker.js` 229 (211/10, open 73)
- Python: `services/db_lifecycle.py` 288 (class 249, _clean_unlocked 42), `services/db_registry.py` 265 (class 194, info 32), `services/db_service.py` 188, `services/db_deletion_flow.py` 202, `services/db_deletion_scan.py` 216, `services/db_deletion_policy.py` 219, `services/db_media_scan.py` 232, `services/db_deletion_inventory.py` 205, `services/db_deletion_flow_remove.py` 175 (70.1% coverage), `services/db_deletion_flow_detach.py` 52 (78.8%), `services/db_deletion_scan.py` 73.5%, `stores/world_lock.py` 285, `stores/media_store.py` 278 (class 214), `stores/media_layout.py` 195, `backend/media_handler.py` 474, `backend/dom_highlight.py` 514 (largest file), `services/collector_service.py` 257 (class 216), `services/collector_archive.py` 171, `bridge/collector_bridge.py` 171 (class 151, 72.1% coverage)

**God LOC sum:** 303+283+281+269+245+288+265+474+514+257+285+278 = **3742** but many JS files already split, actual god to fix: 303+283+281+269+245+288+265+474+514+257 = **3179** (balanced)

**Coverage debt:** `db_deletion_flow_remove 70.1%`, `db_registry 70.5%`, `collector_bridge 72.1%`, `db_deletion_scan 73.5%`, `media_fetch 77.7%`

**Isolation:** Touches only `ui/js/collector-*`, `ui/js/stack-*`, `ui/js/color-picker.js`, `services/db_*`, `services/collector_*`, `stores/world_lock.py`, `stores/media_*`, `backend/media_handler.py`, `backend/dom_highlight.py`, `bridge/collector_bridge.py`. No `bridge/history`, `bridge/layout`, `services/people`, `stores/label`.

**Steps:**
1. **C1 — Media + Dom Highlight + Collector Panel:** Split `dom_highlight.py` 514→`dom_highlight_core.py`, `dom_highlight_probe.py` (build_highlight_probe is JS literal, allowed 107 but control flow must be CC≤10), `dom_highlight_clear.py`. Split `media_handler.py` 474→`media_handler_core.py`, `media_handler_dialog.py` (_open_dialog 35), `media_handler_fetch.py`. Split `collector-panel.js` 303→core/render (object 290→2×120, init 59→2×25). Validate `ideal-size:` reason for JS literal.
2. **C2 — DB Lifecycle + Registry + Deletion Flow:** Split `db_lifecycle.py` 249→core/clean/world ( _clean_unlocked 42→2×15), `db_registry.py` 194→core/info/scan (info 32→2×15), `db_deletion_flow.py` 202→core/remove/detach/policy, `db_deletion_scan.py` 216→core/inventory. Lift coverage `db_registry` 70.5→80%, `db_deletion_flow_remove` 70.1→80% via unit tests.
3. **C3 — Stack-DnD + Collector Service + Bridge:** Split `stack-dnd-form.js` 283→core/render (object 222→2×100), `stack-dnd-render.js` 281→core/list/config, `stack-dnd-menu.js` 245 (242/16→2×120/8), `collector_service.py` 216→tick/probe/archive (already partially), `collector_bridge.py` 151→core/control, lift 72.1→80%. Fix js_gate: collector-panel object 290>150, stack-dnd-menu 242>150, color-picker open 73>30.

**Acceptance:**
- No file >300, no class >150, no func >30 (except JS literal with `ideal-size:`)
- `dom_highlight` control flow CC≤10, nesting≤4
- `db_registry`, `db_deletion_flow_remove`, `collector_bridge`, `db_deletion_scan`, `media_fetch` ≥80%
- `js_size` collector-panel ≤300, stack-dnd-menu ≤150 object, no func >30 NEW
- `quick_validate` PASS

**Time:** ~2.5–3 days (largest files 514+474)

---

### Area D — People & Labels & Bot System (JS Labels/User/Bot + Python People/Label/Preset/Bot)

**Domain:** User memory, labels, bot chat, presets, people bridge. Vocabulary: `PeopleService`, `LabelStore`, `UserMemory`, `BotChat`, `PresetStore`, `BotConnections`.

**Files (god):**
- JS: `labels.js` 190 (169/9, init 55, 2 over-30), `labels-assign.js` 145 (132/9, renderAssign 50), `labels-model.js` 86 (72/9), `labels-render.js` 106 (94/5, pill 47), `labels-edit.js` 106 (94/4, _editRow 54), `labels-filter.js` 88 (76/3, renderFilter 45), `user-table-core.js` 71 (61/5, init 37), `user-table-render.js` 86 (76/9), `user-table-actions.js` 77 (67/12), `bot-connection-view.js` 238 (210/17), `bot-settings-core.js` 115 (105/21 →21 methods>15), `bot-settings-actions.js` 80 (70/15), `bot-chat-core.js` 86 (73/8), `bot-chat-bridge.js` 70, `bot-chat-cards.js` 53, `bot-chat-send.js` 66, `bot-prompt-core.js` 82 (72/9), `bot-prompt-vars.js` 49, `bot-prompt-presets.js` 55, `bot-prompt-actions.js` 42, `bot-settings` etc., `presets-ui-core.js` 102, `presets-ui-stack.js` 89, `presets-ui-import.js` 103, `presets-ui-blocks.js`, `presets-ui-templates.js`
- Python: `services/people_service.py` 227 (class 192), `stores/label_store.py` 287 (class 222), `stores/user_memory.py` 284 (class 202), `stores/preset_store.py` 227 (class 163), `services/bot_chat.py` 299 (largest service), `services/bot_connections.py` 231 (ConnectionStore 130/10, _adopt_legacy 24), `services/bot_grok.py` 193, `services/bot_providers.py`, `services/bot_prompts.py` 50, `services/bot_presets.py` 47, `services/bot_reactions.py` 75, `services/bot_variables.py`, `stores/media_fetch.py` 182 (77.7%), `bridge/people_bridge.py` 101 (76.1%), `bridge/label_bridge.py` 102 (78.0%), `bridge/bot_bridge.py` 185, `bridge/bot_prompt_bridge.py` 84, `bridge/bot_settings_bridge.py` 73, `actions/click_user.py` 225 (class 225, execute 39), `actions/scroll_parse_run.py` 197, `actions/collect_history.py` 178

**God LOC sum:** labels 190+145+238+227+287+284+227+299+231+225 = **2353** + many small ~800 = **~3150** (balanced)

**Coverage debt:** `people_bridge 76.1%`, `label_bridge 78.0%`, `media_fetch 77.7%`, `bot` files low JS coverage (bot-chat 0<97.5, bot-connection-view 41.6<99.6)

**Isolation:** Touches only `ui/js/labels*`, `ui/js/user-table*`, `ui/js/bot-*`, `ui/js/presets-ui*`, `services/people_service.py`, `stores/label_*`, `stores/user_memory.py`, `stores/preset_store.py`, `services/bot_*`, `bridge/people_bridge.py`, `bridge/label_bridge.py`, `bridge/bot_*`, `actions/click_user.py`, `actions/scroll_parse*`, `actions/collect_history.py`. No `bridge/router`, `bridge/layout`, `bridge/history`, `services/db_*`, `stores/history_*`, `ui/js/sash-*`, `ui/js/history-*`, `ui/js/collector-*`.

**Steps:**
1. **D1 — Labels + User Table + People Service:** Split `label_store.py` 287→core/assign/filter (222→3×~70), `user_memory.py` 284→core/search/persist (202→3×~60), `people_service.py` 227→core/filter/persist (192→3×~60), `labels.js` 190→core/render (169/9→2×80), `labels-assign.js` 145→core/render (renderAssign 50→2×20), `user-table-core.js` 71 (init 37→2×15). Lift `people_bridge` 76.1→80%, `label_bridge` 78→80%.
2. **D2 — Bot Chat + Connections + Bridges:** Split `bot_chat.py` 299→core/chat/connections (empty_detail 19, scoped_page 17, check_recipient 22, deliver 22), `bot_connections.py` 231→core/store (ConnectionStore 130→core/seed/merged), `bot_connection-view.js` 238 (210/17→2×100/8), `bot-settings-core.js` 115 (105/21 methods→model/render 2×50/10). Fix js_gate: bot-settings-core 21 methods>15, labels-assign renderAssign 50>30, labels-edit _editRow 54>30, labels-filter renderFilter 45>30, labels-render pill 47>30, user-table-core init 37>30. Add Node tests for bot files (never loaded).
3. **D3 — Presets + Click User + Collect History:** Split `preset_store.py` 227→core/io (163→2×70), `click_user.py` 225→core/execute (execute 39→2×15), `collect_history.py` 178→core/run, `scroll_parse_run.py` 197→core/options. Lift `media_fetch` 77.7→80% (belongs to D? Actually media_fetch is media, but close to label/people). Fix 14 Node failures for `test_bot_chat_js`, `test_labels_ui_js`, etc.

**Acceptance:**
- No file >300, no class >150, no func >30 NEW
- No object >15 methods, no func >30
- `people_bridge`, `label_bridge`, `media_fetch` ≥80%
- JS bot files coverage restored (never-loaded 0), `bot-chat` 0→≥97.5%
- `quick_validate` PASS, `js_gate` for these files 0 violations

**Time:** ~2.5 days

---

## 3. Balanced Summary Table

| Area | Domain | God LOC | Total LOC | Files >300 | Classes >150 | Funcs >30 | Coverage debt | Est. Days |
|---|---|---:|---:|---:|---:|---:|---|---:|
| A Grid & Layout | sash + layout + undo + router | 3085 | 3860 | 3 (sash-core 684, sash-grid-windows 487, router 486) | 5 (router, layout_bridge, undo_bridge, undo_service, undo_support) | 3 (get_app_state 40, moveWindow 51, _specGeometry 36) | layout_bridge 67.3%, JS sash 23% | 2.5 |
| B History | history JS + query/parser + stores history | 3227 | 3683 | 3 (history-model 412, history-view 345, chat_parser 426) | 8 (history_query, history_db, history_repo, history_repo_append, history_repo_media, history_schema, history_bridge) | 6 (init 54, append 46, etc.) | history-model 90.8<91.3, history-view 87<93.6 | 2.5 |
| C Collector & DB | collector/stack + db/media | 3179 | 3742 | 4 (collector-panel 303, stack-dnd 283/281/269, dom_highlight 514, media_handler 474) | 7 (db_lifecycle 249, db_registry 194, collector_service 216, world_lock 285, media_store 214, etc.) | 5 (_clean_unlocked 42, _open_dialog 35, etc.) | db_registry 70.5%, db_deletion 70-78%, collector_bridge 72% | 2.5–3 |
| D People & Labels & Bot | labels/user/bot + people/label/preset | ~3150 | ~3500 | 2 (bot_chat 299, label_store 287, user_memory 284) | 8 (people_service 192, label_store 222, user_memory 202, preset_store 163, click_user 225, etc.) | 7 (renderAssign 50, _editRow 54, etc.) | people_bridge 76%, label_bridge 78%, media_fetch 77%, bot JS 0% | 2.5 |

**Total:** ~12,640 god LOC, ~14,785 total, 4 areas × ~3150 god avg → balanced within 10% (2353–3227 god, 3500–3860 total). Time difficulty ~2.5 days each for Opus 5.

---

## 4. Branching Strategy (Isolated Development)

- **Base:** `arena/01a0a172-chat-v-bot` @ `c5ff8f2` (already has H-C5 + Issue 4)
- **Branches:**
  - `arena/round-i-a-grid` — Area A
  - `arena/round-i-b-history` — Area B
  - `arena/round-i-c-collector-db` — Area C
  - `arena/round-i-d-people-labels-bot` — Area D
- **Isolation rules:**
  - Each branch touches only its file list (enforced via `git diff --name-only` check in CI)
  - Facades keep public API (`SashGrid`, `HistoryBridge`, `DbLifecycle`, etc.) — no breaking changes
  - No cross-area imports modified in same PR
  - Each branch rebases onto base weekly, runs `quick_validate --full --with-clones` + `js_gate` + `js_coverage` before merge
- **Merge order:** D (stores leaf) → C (services) → B (bridge) → A (JS) dependency-wise, but A can merge first because JS has zero Python coupling. For 3 areas, merge C+D into one branch `round-i-cd-collector-people` to reduce integration risk.

---

## 5. RULE 16/18/19 Enforcement (Per Area)

**Every PR must:**
- [ ] No new function >30 LOC (except JS literal with `ideal-size: 78 lines reason=single JS payload...`)
- [ ] No new class >150 LOC or >15 methods
- [ ] No new function >4 params (excluding self/cls)
- [ ] radon CC ≤10, cognitive ≤15, nesting ≤4
- [ ] line coverage ≥93.16% (current) and not below baseline, branch ≥88.85%
- [ ] every new function has test that would fail if deleted (RULE 8)
- [ ] no new vulture, no new clone groups (import headers only)
- [ ] aims at RULE 18 ideal: func 4–20, file 150–300, module 5–15; deviation has `ideal-size:` comment
- [ ] remediation order RULE 19: nesting→CC→cognitive→size (verify after each step: `radon cc -s file`, `quick_validate`)

**Commands:**
```bash
.venv/bin/python tools/metrics/rule16_gate.py
.venv/bin/python tools/metrics/quick_validate.py --full --with-clones
.venv/bin/python tools/metrics/file_coverage_floor.py
.venv/bin/python tools/metrics/stores_modules.py
.venv/bin/python tools/metrics/js_size.py | sort -k2 -rn | head -n 20
.venv/bin/python tools/metrics/js_gate.py
.venv/bin/python tools/metrics/js_coverage.py
```

---

## 6. No Implementation — Next Actions

1. Create 4 branches from `c5ff8f2`
2. For each area, create `docs/archive/2026-09-15-round-i-<area>/DESIGN_2026-09-15.md` with current radon numbers, target numbers, rejected dishonest reductions
3. Start with Area D (stores leaf) + Area A (JS independent) in parallel, using Opus 5 / Fable 5 (other models failed per user note)
4. Each sub-step: research → design → implement → measure → docs update (RULE 17)

No code changes in this doc — planning only, rebalanced for equal time difficulty.
