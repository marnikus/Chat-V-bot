# Round I — Code Quality Remediation Plan — 2026-09-15

**Branch:** `arena/01a0a172-chat-v-bot` @ `33573f7`
**Baseline comparison:** `reports/CODE_QUALITY_METRICS_2026-09-14.md` (5197ce0)
**Rules:** `docs/current/AGENT_RULES.md` RULE 16 (gates) + RULE 18 (ideal sizes) + RULE 19 (nesting→CC→cognitive→size)

> NO implementation in this doc — planning only, per user request.

---

## 1. Current Metrics Snapshot (2026-09-15, post H-C5 + Issue 4 drag split)

### 1.1 Python — Complexity CLOSED, Size Closing

| Metric | 2026-09-14 | **2026-09-15 now** | Delta |
|---|---|---:|---|
| Files >500 LOC | 4 | **3** (dom_highlight 514, router 486, media_handler 474) | -1 |
| Files >300 LOC | 23 | **3** | -20 |
| Classes >150 LOC | 36 | **36** (still, but different set — see §2) | 0 |
| Functions >30 LOC | 39 (1.7%) | **~30** (10 backend + 6 bridge + 15 services + 19 stores + 9 actions, some overlap) | -9 |
| Functions CC>10 | 0 | **0** | clean |
| Functions cognitive>15 | 0 | **0** | clean |
| Nesting >4 | 0 | **0** | clean |
| Mean MI | 68.05 | **~70 est** (need re-run) | + |
| Min MI | 24.9 | **>24.9** (history_bridge still low) | |
| Line coverage | 92.64% | **93.16%** (per quick_validate mini 4 files) | +0.5 |
| Branch coverage | 88.03% | **88.85%** | +0.8 |
| Test : prod ratio | 1:1.57 | **~1:1.6** | |

**Tool outputs (today):**
- `rule16_gate.py`: **PASS** (all owned functions fit, ratchet intact)
- `quick_validate.py`: PASS (double_audit, smell_inventory, file_coverage_floor, rule16_gate, vulture, mutation_config)
- `file_coverage_floor.py`: 9 files below 80% (lowest: `layout_bridge 67.3%`, `db_deletion_flow_remove 70.1%`, `db_registry 70.5%`, `collector_bridge 72.1%`, `db_deletion_scan 73.5%`, `people_bridge 76.1%`, `media_fetch 77.7%`, `label_bridge 78.0%`, `db_deletion_flow_detach 78.8%`) — no ratchet regression.
- `smell_inventory.py`: vulture 7 findings (unchanged), clones 13 groups / 96 lines (import headers only), wide params 11 (mostly RULE 3 block settings, 2 candidates: `router.__init__` 8 params, `chat_sync.run_sync` 5 params)
- `double_audit.py`: 138 doubles, 0 invented interface

### 1.2 JavaScript — The Open Flank (now worse after split)

| Metric | 2026-09-14 | **2026-09-15 now** | Notes |
|---|---|---|---|
| Total JS files | 42 (11,865 LOC) | **85 files / 11,158 LOC** (split) | more files, fewer lines (dedup) |
| Files >500 LOC | 1 (sash-grid 1,361) | **2** (chat_agent 803, sash-core 684) | - |
| Files >300 LOC | ~5 | **5** (sash-core 684, sash-grid-windows 487, history-model 412, history-view 345, collector-panel 303) | still |
| Functions >30 LOC | 49 (baseline) | **37** | -12 |
| Largest gated object | SashGrid 1,331 LOC / 69 methods | **collector-panel 290 LOC / 15 methods, app-bridge 270/15, stack-dnd-menu 242/16** | split helped |
| JS line coverage | 82.8% | **69.49%** (5365/7721) | **-13%** — regression due to many new split files never loaded |
| Never-loaded files | 6 (1,239 LOC) | **~40** (list in js_gate) | split files not covered by Node tests |
| Node suites failed | 0 | **14** | `test_bot_chat_js`, `test_db_panel_js`, `test_grid_close_autosave`, etc. — Qt-less env |

**`js_gate.py` today: 86 violations**
- size: 14 (bot-settings-core 21 methods >15, 7 NEW functions >30, sash-core 684>642 baseline, sash-core anon 619→661, moveWindow 43→51, drag-core object 194>150, drag-spec object 159>150, _specGeometry 36>30, etc.)
- coverage: 72 (15 baseline drops: bot-chat 0<97.5, bot-connection-view 41.6<99.6, ... sash-grid-windows 23.4<68.2, sash-grid 0<99.1, plus 40 NEW files never loaded, total 69.49<82.52, 14 Node suite failures)

**Interpretation:** Python complexity is done. Python size tail shrank from 23→3 files >300, but class-size tail (36 classes >150) remains. JS is now the single biggest structural debt: 5 files >300, 37 functions >30, 86 gate violations, coverage down 13%.

---

## 2. Prioritized Problems (RULE 19 order: nesting→CC→cognitive→size)

### P0 — JS God Objects & Coverage Collapse (RULE 18, RULE 16 mirror)
- **Where:** `ui/js/sash-core.js` 684 LOC / 46 funcs / 3 over-30 (moveWindow 51), `sash-grid-windows.js` 487 LOC / 58 funcs / 14 methods object, `history-model.js` 412 LOC / 4 over-30, `history-view.js` 345 LOC / 5 over-30, `collector-panel.js` 303 LOC / 15 methods, `bot-settings-core.js` 21 methods >15.
- **Why P0:** Largest files in repo, 2.3× biggest Python file, violates RULE 18 ideal 150–300, RULE 16 mirror (js_gate) FAIL, coverage regression blocks CI.
- **Metrics:** JS size 11k LOC, 86 violations, coverage 69% < 82% baseline.

### P1 — Bridge Layer Spine (Coupling & Size)
- **Where:** `bridge/router.py` 486 LOC (was 544, still god), `history_bridge.py` class 180 LOC / 62 line, `layout_bridge.py` 176 / 40 LOC func `get_app_state`, `undo_bridge.py` 165, `collector_bridge.py` 151.
- **Why P1:** High efferent coupling (router touches every bridge), low coverage (`layout_bridge 67.3%`, `collector_bridge 72.1%`), MI low (history_bridge MI 24.9 worst file), wide params `router.__init__` 8 params.
- **Metrics:** 4 classes >150, 1 file >400, 2 files below 80% coverage.

### P2 — Services Layer — God Services
- **Where:** `services/db_lifecycle.py` class 249 LOC (was 511, split but still over), `collector_service.py` 216, `db_registry.py` 194, `people_service.py` 192, `undo_service.py` 182, `run/coordinator.py` 182, `run/error_recovery.py` 163, `undo_support.py` 153.
- **Why P2:** 8 classes >150, core business logic, file_coverage_floor shows `db_registry 70.5%`, `db_deletion_*` 70–78% (related).
- **Metrics:** Mean MI ~45 for these files, below repo mean 68.

### P3 — Stores Layer — Data Access Monoliths
- **Where:** `stores/history_repo_append.py` 237, `history_db.py` 232 (init 54 LOC), `history_repo.py` 225, `label_store.py` 222, `media_store.py` 214, `history_repo_media.py` 206 (recover_media 36), `user_memory.py` 202, `history_schema_repair.py` 193, `preset_store.py` 163, `history_schema_legacy.py` 155.
- **Why P3:** 10 classes >150, many functions >30 (append 46, _write_rows 41, _prepend 41), file `history_db.py` 300 LOC exact, coverage OK but churn high.
- **Metrics:** Stores is 37 files counted as 15 modules via families — cohesion OK but size still high.

### P4 — Actions Layer (smaller, but still)
- **Where:** `actions/click_user.py` 225, `scroll_parse_run.py` 197, `collect_history.py` 178.
- **Why P4:** 3 classes >150, but already split in Round G, lower priority.

**Overall:** P0 is biggest (JS), then P1 (bridge), then P2/P3 (services/stores) roughly equal. P4 can be deferred.

---

## 3. Split Into 3–4 Isolated Areas (for parallel branches)

**Principle:** Each area owns a directory/file family, no cross-area imports changed in same PR, RULE 16 gate must stay PASS, RULE 18 ideal checked at end, JS gate for Area A.

### Area A — JS Frontend Remediation (JS Gate + Sash-Grid/Stack-DnD)

**Owner:** `ui/js/` + `tests/test_*.js` (Node)
**Scope:**
- `sash-core.js` 684 → split into `sash-core-tree.js` (defaultTree, PRESETS, constructors), `sash-core-ops.js` (splitLeaf, insertAtSplitIndex, insertSibling, insertBetween, insertOuter, moveWindow), `sash-core-validate.js` (validate, pruneTree, migrate, serialize/deserialize, leafIds, findNode)
- `sash-grid-windows.js` 487 → `sash-grid-window-store.js` (collectPanels, load/save), `sash-grid-window-ops.js` (close/open/minimize), `sash-grid-menus.js` (dock, menus) — already partially split but still 487, need further
- `history-model.js` 412 → `history-model-core.js`, `history-model-search.js`, `history-model-render.js`
- `history-view.js` 345 → `history-view-core.js`, `history-view-events.js`
- `collector-panel.js` 303 → `collector-panel-core.js`, `collector-panel-render.js`
- `bot-settings-core.js` 21 methods → split into `bot-settings-model.js` + `bot-settings-render.js`
- Fix `js_gate` violations: 7 NEW funcs >30 → extract helpers, objects >150 → split, NEW files never loaded → add Node tests loading them (like `test_sash_drag.js` pattern)
- Restore coverage: add `tests/test_sash_*.js` loaders, fix 14 failing Node suites (likely missing `SashCore` mock)

**Steps:**
1. Research: `js_size.py` + `js_coverage.py` baseline, list largest objects/methods
2. Design: doc per file split (responsibility, public API unchanged, `UIHelpers.mergeParts` pattern)
3. Implement: split one file at a time, keep facade (`sash-core.js` facade re-exports), update `ui/index.html` script order
4. Validate: `js_size.py` (no file >500, no new func >30, object <150), `js_gate.py` violations decreasing, `js_coverage.py` coverage increasing, `node tests/test_sash_core.js` green

**Acceptance:**
- No JS file >300 LOC (ideal), max 500 (hard)
- No object >15 methods, no func >30 LOC NEW
- Coverage ≥82.52% baseline, no NEW file never loaded
- Node suites 0 failed

**Isolation:** Only touches `ui/js/`, `ui/index.html`, `tests/test_*.js`, `tools/metrics/js_*` baselines. No Python.

### Area B — Bridge Layer Spine (Router + History/Layout/Undo/Collector Bridges)

**Owner:** `bridge/` + `services/run/hooks.py` (wide params)
**Scope:**
- `bridge/router.py` 486 LOC → split into `router-core.js` (init, ctx, undo), `router-history.js`, `router-layout.js`, `router-collector.js`, `router-people.js` — aim 5 files × ~100 LOC, each ≤150
- `history_bridge.py` 180 LOC class → `history_bridge_core.py` (init, _db), `history_bridge_search.py` (search, filter), `history_bridge_delete.py` (already exists, expand), `history_bridge_append.py`
- `layout_bridge.py` 176 + func `get_app_state` 40 LOC → `layout_bridge_state.py` (get_app_state), `layout_bridge_persist.py` (save/load)
- `undo_bridge.py` 165 → `undo_bridge_core.py`, `undo_bridge_history.py`
- `collector_bridge.py` 151 → `collector_bridge_core.py`, `collector_bridge_control.py`
- Fix wide params: `router.__init__` 8 params → options object `RouterOptions`, `chat_sync.run_sync` 5 params → `SyncRequest`
- Coverage: `layout_bridge 67.3%`, `collector_bridge 72.1%`, `people_bridge 76.1%`, `label_bridge 78.0%` → add unit tests

**Steps:**
1. Research: radon CC (all 0), but class LOC 150–180, file LOC 486, coupling Ce high (router imports all bridges)
2. Design: dependency diagram, ensure `bridge/` → `services/` direction (no `services` → `bridge`), options object pattern, facade `router.py` keeps public API
3. Implement: split router first (biggest), then each bridge class via mixin pattern `UIHelpers.mergeParts` equivalent for Python: `class HistoryBridge(HistoryBridgeCore, HistoryBridgeSearch, ...)` or composition
4. Validate: `rule16_gate.py` PASS (no class >150 NEW, but legacy ratchet must not grow), `file_coverage_floor.py` no new below-floor, coverage of touched files ≥80%, `wc -l bridge/*.py` all ≤300

**Acceptance:**
- `router.py` ≤150 LOC facade, 5 parts ≤150 each
- No bridge class >150 LOC, no method >30 LOC
- `router.__init__` ≤4 params (options object)
- Coverage of `layout_bridge`, `collector_bridge` ≥80%
- No new clone groups (import headers only)

**Isolation:** Only `bridge/` + `services/run/hooks.py` + tests in `tests/unit/bridge/`. No `stores/` or `ui/js/`.

### Area C — Services Layer (DB Lifecycle, Registry, Collector, People, Undo, Run)

**Owner:** `services/` + `services/run/` + `services/history/`
**Scope:**
- `db_lifecycle.py` 249 LOC class → `db_lifecycle_core.py` (init, _db), `db_lifecycle_clean.py` (_clean_unlocked 42 LOC), `db_lifecycle_world.py` (world creation)
- `db_registry.py` 194 + `info` 32 LOC → `db_registry_core.py`, `db_registry_info.py`, `db_registry_scan.py`
- `collector_service.py` 216 class → `collector_tick.py` (already split), `collector_probe.py`, `collector_archive.py`, `collector_service.py` facade
- `people_service.py` 192 → `people_service_core.py`, `people_service_filter.py`, `people_service_persist.py`
- `undo_service.py` 182 + `undo_support.py` 153 + `undo_world.py` 31 → `undo_service_core.py`, `undo_support.py` (already split?), `undo_apply.py`, `undo_archive.py`
- `run/coordinator.py` 182 + `error_recovery.py` 163 + `cycle_plan.py` `choose_cycle_mode` 31 → `run/coordinator.py` facade, `run/lifecycle.py`, `run/cycle.py`, `run/error_recovery.py` split
- `bot_chat.py` 299 LOC file (largest service file) — belongs to Area C or separate? Keep for now, but note 299 LOC near limit.

**Steps:**
1. Research: list classes >150, functions >30 (`_clean_unlocked` 42, `find_tab_by_url` 38, `schedule_save` 36, `choose_cycle_mode` 31), MI lowest among services
2. Design: per class, identify single responsibilities (e.g., DbLifecycle: world list, clean, lock, backup), use composition over inheritance, keep `services/db_lifecycle.py` as facade re-exporting
3. Implement: split one god class at a time, keep tests green (`tests/unit/services/`), add coverage for below-floor files (`db_registry`, `db_deletion_*`)
4. Validate: `rule16_gate.py` PASS, `wc -l services/*.py` ≤300, class LOC ≤150, `file_coverage_floor.py` — `db_registry` and `db_deletion_*` should move ≥80%

**Acceptance:**
- No service file >300 LOC, no class >150 LOC
- No function >30 LOC
- `db_registry` ≥80%, `db_deletion_flow_remove/scan` ≥80%
- No new vulture findings

**Isolation:** Only `services/` + `services/run/` + `services/history/` + `stores/` read-only (no writes to stores). No `bridge/` or `ui/js/`.

### Area D — Stores Layer (History Repo, History DB, Label Store, Media Store, User Memory)

**Owner:** `stores/` + `services/db_*` (read)
**Scope:**
- `history_repo_append.py` 237 (AppendPlanner) + funcs `append` 46, `_write_rows` 41, `_prepend` 41 → `history_repo_append_core.py`, `history_repo_append_write.py`, `history_repo_append_prepend.py`
- `history_db.py` 300 + `init` 54 → `history_db_core.py` (init split into `_init_tables`, `_init_indexes`), `history_db_query.py`, `history_db_write.py`
- `history_repo.py` 225 → `history_repo_core.py`, `history_repo_query.py`, `history_repo_mutate.py`
- `label_store.py` 222 → `label_store_core.py`, `label_store_assign.py`, `label_store_filter.py`
- `media_store.py` 214 → `media_store_core.py`, `media_store_fetch.py`, `media_store_layout.py`
- `history_repo_media.py` 206 + `recover_media` 36 → `history_repo_media_core.py`, `history_repo_media_recover.py`
- `user_memory.py` 202 → `user_memory_core.py`, `user_memory_search.py`, `user_memory_persist.py`
- `history_schema_repair.py` 193 → `history_schema_repair_core.py`, `history_schema_repair_migrate.py`
- `preset_store.py` 163 → `preset_store_core.py`, `preset_store_io.py`
- `history_schema_legacy.py` 155 + `_rebuild_messages_constraint` 31 → split

**Steps:**
1. Research: `stores_modules.py` to ensure family count stays 15, `clone_scan.py` to avoid duplicating SQL/report strings
2. Design: each store has single domain (history, labels, media, user_memory), keep `stores/json_store.py` + `atomic.py` as write layer, no cross-store imports (import graph check)
3. Implement: split god classes, keep facade files (e.g., `history_repo.py` imports from parts), ensure `leafIds` etc. unchanged, add tests for `init` 54 LOC split
4. Validate: `stores_modules.py` PASS (15 modules), `rule16_gate.py` PASS, `wc -l stores/*.py` ≤300, class ≤150, `file_coverage_floor.py` — `media_fetch` 77.7% should go ≥80%

**Acceptance:**
- No store file >300, no class >150, no func >30
- `stores_modules.py` still reports 15 modules, no new family
- `file_coverage_floor.py` — `media_fetch` ≥80%, no new below-floor
- No new clone groups

**Isolation:** Only `stores/` + `tests/unit/stores/` + `tools/metrics/stores_modules.py`. No `services/` or `bridge/`.

---

## 4. Cross-Area Dependencies & Order

- **Area A** (JS) is fully independent — no Python imports. Can start immediately, any branch.
- **Area B** (bridge) depends on **Area C/D** only via `services/` and `stores/` interfaces, but does not modify them. Can start after C/D facades stable, or in parallel if only reading.
- **Area C** (services) depends on **Area D** (stores) for `history_db`, `label_store`, etc. — should start after D facades, or parallel with D if D keeps facades.
- **Area D** (stores) is leaf — no dependencies on B/C, only on `stores/json_store` write layer. Can start first.

**Recommended order:**
1. **D** (stores) → **C** (services) → **B** (bridge) → **A** (JS) in terms of dependency, but **A** can run in parallel from day 0 because it touches different language.
2. For 3 branches: `arena/round-i-a-js`, `arena/round-i-b-bridge`, `arena/round-i-c-services-stores` (merge C+D into one branch to reduce integration risk, as they are tightly coupled).
3. For 4 branches: as listed A/B/C/D.

**Integration:** Each branch rebases onto `main` (or `arena/01a0a172-chat-v-bot` which already has H-C5 + Issue 4), runs `quick_validate.py --full --with-clones` before merge.

---

## 5. RULE 16 & RULE 18 Enforcement Plan

**Every production change must:**
- [ ] No new function >30 LOC (except documented JS-literal builders with `ideal-size:` reason)
- [ ] No new class >150 LOC or >15 methods
- [ ] No new function >4 params (excluding self/cls)
- [ ] radon CC ≤10, cognitive ≤15, nesting ≤4
- [ ] overall line coverage ≥80% and not below baseline (93.16%/88.85% now); branch ≥75%
- [ ] every new function has test that would fail if deleted (RULE 8)
- [ ] no new vulture, no new duplication groups
- [ ] aims at RULE 18 ideals: func 4–20, file 150–300, module 5–15 files; deviation has `ideal-size:` comment
- [ ] remediation followed RULE 19 order (nesting→CC→cognitive→size)

**Tools (copy-paste):**
```bash
# Python gates
.venv/bin/python tools/metrics/rule16_gate.py
.venv/bin/python tools/metrics/quick_validate.py --full --with-clones
.venv/bin/python tools/metrics/file_coverage_floor.py
.venv/bin/python tools/metrics/stores_modules.py

# JS gates
.venv/bin/python tools/metrics/js_size.py | sort -k2 -rn | head -n 20
.venv/bin/python tools/metrics/js_gate.py
.venv/bin/python tools/metrics/js_coverage.py | tail -n 20

# Complexity
.venv/bin/python -m radon cc -s backend/*.py bridge/*.py services/**/*.py stores/*.py app/*.py | grep -E " C | D | E | F "
.venv/bin/python -m radon raw --summary backend/*.py bridge/*.py services/**/*.py stores/*.py app/*.py
```

---

## 6. New Round Steps (High-Level)

**Round I-0 (this doc):** Planning — metrics, prioritization, 4 areas, no code.

**Round I-A (JS):**
- I-A1: sash-core split (tree/ops/validate) + tests
- I-A2: sash-grid-windows split (store/ops/menus) + tests
- I-A3: history-model/view + collector-panel split + js_gate green

**Round I-B (Bridge):**
- I-B1: router split (core/history/layout/collector/people) + options object
- I-B2: history_bridge + layout_bridge split + coverage lift to 80%
- I-B3: undo_bridge + collector_bridge split + clone check

**Round I-C (Services):**
- I-C1: db_lifecycle + db_registry split + coverage
- I-C2: collector_service + people_service split
- I-C3: undo_service + run/coordinator split

**Round I-D (Stores):**
- I-D1: history_repo_append + history_db split
- I-D2: history_repo + label_store + media_store split
- I-D3: user_memory + schema_repair + preset_store split + stores_modules check

Each sub-step: research (radon, wc -l, coverage), design doc in `docs/archive/2026-09-15-round-i-<area>/`, implement, measure, update `SYSTEM_OF_RECORD.md` if behaviour moves.

---

## 7. Risks & Mitigations

- **JS coverage collapse:** New split files not loaded → add `test_sash_*.js` loaders (pattern from `test_sash_drag.js`), fix 14 failing Node suites (likely missing global mocks).
- **Bridge router coupling:** Router imports every bridge → split must keep facade `router.py` with same public API, no circular imports.
- **Stores family count:** `stores/` is 37 files counted as 15 modules via prefix families — new files must belong to existing family or update `stores_modules.py` with justification (RULE 18 §18.3).
- **Clone scan:** Import headers cause false clones — ensure `clone_scan.py` reports only shared headers, not copied logic.
- **Coverage floor:** 9 files below 80% — touching them without lifting coverage fails gate. Add tests first (RULE 16 §16.6 step 3).

---

## 8. Acceptance for Round I

- [ ] Python: 0 files >300 LOC, 0 classes >150 LOC, 0 funcs >30 LOC (except JS-literal), CC>10=0, cognitive>15=0, nesting>4=0
- [ ] JS: 0 files >300 LOC (max 500 hard), 0 objects >15 methods, 0 funcs >30 NEW, coverage ≥82.52%, 0 never-loaded, 0 Node failures
- [ ] Coverage: line ≥93.16%, branch ≥88.85%, no file below 80% (or ratchet updated with justification)
- [ ] Clones: 13 groups / 96 lines, no new groups
- [ ] Stores modules: 15, import graph clean
- [ ] All 4 areas merged, `quick_validate.py --full --with-clones` PASS, `js_gate.py` PASS

---

**Next action:** Create branches `arena/round-i-a-js`, `arena/round-i-b-bridge`, `arena/round-i-c-services`, `arena/round-i-d-stores` from `arena/01a0a172-chat-v-bot`, and start with Area D (stores) as leaf dependency, in parallel with Area A (JS) which is independent.

No code changes in this commit — planning only.
