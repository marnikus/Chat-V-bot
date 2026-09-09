# 🧭 Chat-V-bot — Refactor Split Into 4 Independent Areas

> **Type:** architecture research + plan (design doc — no implementation in this PR)
> **Date:** 2026-09-09 · **Base commit:** `392fdff` (+ working-tree hotfixes `DEFAULT_URLS` /
> fake-`PySide6` — see §2.4)
> **Source data:** `reports/CODE_QUALITY_METRICS_2026-09-09.md` + fresh re-measurement
> (108 production modules, 1,640 tests, 201 commits)
> **Status:** ✅ research done · ⏳ awaiting approval to implement

---

## 0. Executive summary

The app is **mid-refactor and currently broken**: 314 of 1,640 tests are red (19.2 %), the
stores↔`ConfigManager` contract is inconsistent, and `services/run/coordinator.py` has two
undefined names that crash stack loading. But the *layering* work already landed
(`core/ → stores/ → services/ → bridge/ → app/`), so the remaining work decomposes cleanly.

**This doc partitions every production file into 4 disjoint, dependency-ordered areas**
(+ 17 frozen files that nobody touches), proves they are independent, and gives the merge
plan.

| Area | Name | Prod. files | SLOC | What it fixes | Branch |
|---|---|---|---|---|---|
| **A** | Boot & state contract | 12 | 1,044 | 116 of 225 error lines — app boots, stores agree with `ConfigManager` | `fix/area-a-state-contract` |
| **D** | Data & parsing layer | 19 | 6,188 | god objects (`HistoryRepo` MI 0.0), `sync_conversation` CC 130, JS parser | `refactor/area-d-data-layer` |
| **C** | Runtime (actions + services + automation) | 43 | 5,397 | `Collector._tick` CC 82, `UndoService` CC 34, `get_action_class` crash, 0 % mutation modules | `refactor/area-c-runtime` |
| **B** | Shell, compat shims & test suite | 17 | 330 | `main.py`/`app/` entry API, 12 compat shims, restore **382 deleted tests** | `test/area-b-safety-net` |
| ❄️ | **Frozen** (no area) | 17 | 2,362 | `core/*` (clean) + `bridge/*` (excluded by design) | — |

**Expected outcome** (measured gates in §7.3):

| Metric | now | after A | after all 4 |
|---|---|---|---|
| failing tests | 314 | ~150 | **0** |
| line / branch coverage | 77.2 % / 68.9 % | 79 % / 71 % | **≥ 85 % / ≥ 78 %** |
| mutation score (sample) | 49.6 % | 55 % | **≥ 70 %** |
| mean Maintainability Index | 64.0 | 66 | **≥ 72** |
| duplication (py / js) | 8.7 % / 9.6 % | — | **< 5 % / < 6 %** |
| vulture findings | 201 | — | **< 40** |
| god classes (>15 methods) | 15 | — | **≤ 5** |

---

## 1. 📊 Research statistics

### 1.1 Global

| Fact | Value |
|---|---|
| production Python | 108 files · 18,250 LOC · 13,852 SLOC · 120 classes · 1,067 functions |
| production JS | 23 files · 8,455 SLOC · 852 functions (lizard: avg CCN 3.6, 21 fns > 10) |
| tests | 95 Python files (19,413 SLOC) + 22 JS files (6,295 SLOC) → ratio 1.15 : 1 |
| suite | **1,323 pass / 314 fail** / 2 skipped / 1 xfailed (19.2 % red) |
| history | 201 commits in 6 days; **63 (31 %) are fix/bug/revert** |
| duplication | Python **8.66 %** (1,387 / 16,005 · 79 groups) · JS **9.59 %** (811 / 8,455 · 52 groups) |
| dead code | 201 vulture findings ≥ 60 % conf. (**7 ≥ 90 %**, 5 at 100 %) · 1 module fully unused |
| MI | mean **64.0**, median 62.3 · A 100 / B 6 / **C 2** (`stores/history_repo.py` 0.0, `backend/chat_parser.py` 6.3) |
| churn | top: `backend/bridge.py` 38, `ui/js/stack-dnd.js` 35, `backend/action_engine.py` 24, `main.py` 18 |

### 1.2 Every module: LOC · coupling · issues · priority

Legend — `Ce→` internal modules this file imports (efferent), `←Ca` internal modules
importing it (afferent), `I = Ce/(Ca+Ce)`, `CCmax` highest cyclomatic complexity inside,
`MI` maintainability index, `Cov%` line coverage. **Pri** is the score from §4.1.

| Area | File | LOC | Ce→ | ←Ca | I | CCmax | MI | Cov% | Issues | Pri |
|---|---|---|---|---|---|---|---|---|---|---|
| A | `backend/config_manager.py` | 313 | 9 | 3 | 0.75 | 17 | 42 | 56 | P0-bug,CC>10,SLOC>200,cov<60,hub,tests-red(113) | **P0** (24) |
| C | `services/run/coordinator.py` | 127 | 5 | 0 | 1.00 | 31 | 21 | 95 | P0-bug,MI<40,CC>25,dead,params>4,tests-red(25),no-direct-tests | **P0** (23) |
| C | `services/collector_service.py` | 776 | 4 | 2 | 0.67 | 82 | 12 | 87 | MI<20,CC>25,SLOC>300,LCOM4>=4,dup>50L,dead,params>4 | **P0** (20) |
| C | `services/undo_service.py` | 661 | 4 | 3 | 0.57 | 34 | 10 | 28 | MI<20,CC>25,SLOC>300,cov<60,LCOM4>=4,params>4 | **P0** (20) |
| B | `app/window.py` | 128 | 0 | 1 | 0.00 | 6 | 34 | 42 | P0-bug,MI<40,cov<60,dead,tests-red(1) | **P0** (20) |
| D | `stores/history_repo.py` | 1230 | 2 | 4 | 0.33 | 34 | 0 | 93 | MI<20,CC>25,SLOC>300,LCOM4>=4,dead,params>4 | **P0** (18) |
| D | `stores/media_store.py` | 750 | 1 | 2 | 0.33 | 32 | 9 | 82 | MI<20,CC>25,SLOC>300,LCOM4>=4,dead,params>4 | **P0** (18) |
| D | `stores/label_store.py` | 555 | 0 | 2 | 0.00 | 28 | 14 | 76 | MI<20,CC>25,SLOC>300,cov<80,LCOM4>=4,dead | **P0** (18) |
| D | `backend/chat_parser.py` | 652 | 2 | 3 | 0.40 | 130 | 6 | 81 | MI<20,CC>25,SLOC>300,dead,params>4 | **P0** (16) |
| FROZEN | `bridge/history_bridge.py` | 511 | 1 | 1 | 0.50 | 12 | 23 | 54 | MI<40,CC>10,SLOC>300,cov<60,LCOM4>=4,dup>50L,dead | **P0** (16) |
| C | `services/db_service.py` | 612 | 0 | 2 | 0.00 | 21 | 15 | 74 | MI<20,CC>10,SLOC>300,cov<80,LCOM4>=4 | **P0** (15) |
| D | `backend/scroll_parser.py` | 495 | 5 | 2 | 0.71 | 43 | 35 | 92 | MI<40,CC>25,SLOC>300,LCOM4>=4,dead,params>4 | **P0** (14) |
| A | `stores/bookmark_store.py` | 44 | 2 | 1 | 0.67 | 4 | 63 | 80 | P0-bug,tests-red(3) | **P0** (14) |
| A | `stores/block_store.py` | 62 | 2 | 1 | 0.67 | 8 | 58 | 72 | P0-bug,cov<80,dead | **P1** (12) |
| D | `stores/history_db.py` | 757 | 1 | 6 | 0.14 | 23 | 32 | 89 | MI<40,CC>10,SLOC>300,LCOM4>=4,dead | **P1** (11) |
| D | `backend/history_query.py` | 420 | 1 | 2 | 0.33 | 22 | 28 | 94 | MI<40,CC>10,SLOC>300,LCOM4>=4,params>4 | **P1** (11) |
| D | `backend/cdp_client.py` | 311 | 0 | 22 | 0.00 | 13 | 35 | 61 | MI<40,CC>10,SLOC>200,cov<80,hub,dead | **P1** (11) |
| C | `services/history/mutate.py` | 177 | 0 | 0 | 0.00 | 19 | 19 | 73 | MI<20,CC>10,cov<80,dead,no-direct-tests | **P1** (11) |
| FROZEN | `bridge/layout_bridge.py` | 187 | 2 | 1 | 0.67 | 13 | 52 | 50 | CC>10,cov<60,dead,tests-red(15) | **P1** (11) |
| C | `services/history/export.py` | 153 | 1 | 0 | 1.00 | 25 | 16 | 80 | MI<20,CC>10,cov<80,dead,no-direct-tests | **P1** (11) |
| A | `stores/labels_file_store.py` | 60 | 1 | 1 | 0.50 | 3 | 87 | 97 | P0-bug,dead | **P1** (11) |
| A | `stores/undo_store.py` | 57 | 2 | 1 | 0.67 | 4 | 60 | 76 | P0-bug,cov<80 | **P1** (11) |
| B | `main.py` | 49 | 4 | 0 | 1.00 | 2 | 60 | 78 | P0-bug,cov<80,no-direct-tests | **P1** (11) |
| D | `backend/dom_highlight.py` | 465 | 1 | 2 | 0.33 | 17 | 51 | 95 | CC>10,SLOC>300,dup>50L,dead,params>4 | **P1** (10) |
| FROZEN | `bridge/router.py` | 455 | 14 | 1 | 0.93 | 10 | 44 | 79 | SLOC>300,cov<80,dup>50L,hub,dead,params>4 | **P1** (10) |
| FROZEN | `bridge/stack_bridge.py` | 320 | 1 | 1 | 0.50 | 7 | 40 | 34 | MI<40,SLOC>200,cov<60,dup>50L,dead | **P1** (10) |
| D | `backend/message_injector.py` | 454 | 2 | 3 | 0.40 | 14 | 43 | 68 | CC>10,SLOC>300,cov<80,dead,params>4 | **P1** (9) |
| C | `actions/scroll_parse.py` | 283 | 4 | 0 | 1.00 | 18 | 56 | 90 | CC>10,SLOC>200,LCOM4>=4,dead,params>4 | **P1** (9) |
| C | `services/run/progress.py` | 181 | 3 | 0 | 1.00 | 14 | 19 | 87 | MI<20,CC>10,no-direct-tests | **P1** (9) |
| C | `backend/media_handler.py` | 360 | 3 | 1 | 0.75 | 26 | 50 | 90 | CC>25,SLOC>200,params>4 | **P2** (8) |
| C | `actions/collect_history.py` | 204 | 3 | 0 | 1.00 | 35 | 48 | 78 | CC>25,cov<80,dead,params>4 | **P2** (8) |
| C | `services/history/query.py` | 155 | 0 | 0 | 0.00 | 11 | 28 | 88 | MI<40,CC>10,LCOM4>=4,dead,no-direct-tests | **P2** (8) |
| FROZEN | `bridge/label_bridge.py` | 156 | 1 | 1 | 0.50 | 6 | 52 | 39 | cov<60,dead,tests-red(2) | **P2** (8) |
| C | `actions/click_user.py` | 209 | 3 | 0 | 1.00 | 31 | 52 | 85 | CC>25,dead,params>4 | **P2** (7) |
| D | `stores/history_models.py` | 196 | 0 | 4 | 0.00 | 15 | 56 | 100 | CC>10,LCOM4>=4,dead,params>4 | **P2** (7) |
| FROZEN | `bridge/undo_bridge.py` | 173 | 4 | 1 | 0.80 | 11 | 47 | 32 | CC>10,cov<60,dead | **P2** (7) |
| C | `actions/wait_page.py` | 82 | 3 | 0 | 1.00 | 18 | 58 | 22 | CC>10,cov<60,dead,no-direct-tests | **P2** (7) |
| D | `stores/user_memory.py` | 266 | 0 | 6 | 0.00 | 14 | 43 | 99 | CC>10,SLOC>200,dead | **P2** (6) |
| A | `stores/preset_store.py` | 244 | 1 | 3 | 0.25 | 11 | 40 | 90 | CC>10,SLOC>200,dead | **P2** (6) |
| C | `services/run/error_recovery.py` | 179 | 1 | 0 | 1.00 | 15 | 26 | 83 | MI<40,CC>10,params>4,no-direct-tests | **P2** (6) |
| C | `backend/visual_click.py` | 187 | 4 | 4 | 0.50 | 27 | 57 | 91 | CC>25,params>4 | **P2** (6) |
| B | `backend/preset_store.py` | 5 | 1 | 0 | 1.00 | 0 | 100 | 0 | cov<60,shim,UNUSED | **P2** (6) |
| D | `backend/dom_probe.py` | 217 | 0 | 7 | 0.00 | 14 | 65 | 98 | CC>10,dead,params>4 | **P2** (5) |
| C | `services/layout_service.py` | 203 | 0 | 3 | 0.00 | 19 | 42 | 98 | CC>10,LCOM4>=4 | **P2** (5) |
| FROZEN | `bridge/collector_bridge.py` | 147 | 1 | 1 | 0.50 | 11 | 52 | 70 | CC>10,cov<80,dead | **P2** (5) |
| C | `services/run/hooks.py` | 151 | 0 | 0 | 0.00 | 8 | 32 | 95 | MI<40,LCOM4>=4,dead,no-direct-tests | **P2** (5) |
| FROZEN | `bridge/db_bridge.py` | 135 | 2 | 1 | 0.67 | 8 | 59 | 92 | dead,tests-red(20) | **P2** (5) |
| C | `actions/mark_messaged.py` | 86 | 2 | 0 | 1.00 | 16 | 70 | 76 | CC>10,cov<80,dead | **P2** (5) |
| C | `actions/take_person.py` | 91 | 2 | 0 | 1.00 | 12 | 76 | 79 | CC>10,cov<80,dead | **P2** (5) |
| C | `actions/click_send.py` | 81 | 4 | 0 | 1.00 | 4 | 73 | 35 | cov<60,dead,params>4,no-direct-tests | **P2** (5) |
| FROZEN | `core/result.py` | 105 | 0 | 10 | 0.00 | 2 | 100 | 100 | LCOM4>=4,hub,dead | **P2** (5) |
| FROZEN | `bridge/cdp_bridge.py` | 118 | 1 | 1 | 0.50 | 4 | 61 | 44 | cov<60,dead | **P3** (4) |
| B | `app/lifecycle.py` | 62 | 0 | 1 | 0.00 | 9 | 52 | 16 | cov<60,params>4 | **P3** (4) |
| C | `services/run/state_machine.py` | 68 | 0 | 0 | 0.00 | 3 | 49 | 88 | tests-red(1),no-direct-tests | **P3** (4) |
| C | `actions/pause.py` | 33 | 2 | 0 | 1.00 | 3 | 75 | 46 | cov<60,dead,no-direct-tests | **P3** (4) |
| FROZEN | `core/events.py` | 185 | 0 | 18 | 0.00 | 3 | 70 | 99 | hub,dead | **P3** (3) |
| D | `backend/tab_matcher.py` | 130 | 0 | 1 | 0.00 | 20 | 56 | 92 | CC>10 | **P3** (3) |
| D | `backend/criteria_engine.py` | 102 | 0 | 2 | 0.00 | 7 | 58 | 99 | LCOM4>=4,dead | **P3** (3) |
| A | `stores/migration.py` | 117 | 1 | 1 | 0.50 | 20 | 72 | 92 | CC>10 | **P3** (3) |
| C | `actions/registry.py` | 109 | 0 | 3 | 0.00 | 7 | 70 | 100 | LCOM4>=4,dead | **P3** (3) |
| FROZEN | `core/interfaces.py` | 113 | 0 | 0 | 0.00 | 1 | 100 | 100 | LCOM4>=4,dead | **P3** (3) |
| C | `actions/context.py` | 78 | 0 | 0 | 0.00 | 4 | 85 | 87 | LCOM4>=4,dead | **P3** (3) |
| FROZEN | `bridge/people_bridge.py` | 149 | 2 | 1 | 0.67 | 5 | 62 | 66 | cov<80,dead | **P3** (2) |
| D | `backend/person_filter.py` | 132 | 0 | 3 | 0.00 | 10 | 62 | 98 | dead,params>4 | **P3** (2) |
| C | `actions/custom_find.py` | 109 | 4 | 0 | 1.00 | 8 | 74 | 96 | dead,params>4 | **P3** (2) |
| C | `actions/attach_image.py` | 82 | 3 | 0 | 1.00 | 4 | 80 | 88 | dead,params>4 | **P3** (2) |
| C | `actions/base.py` | 92 | 1 | 1 | 0.50 | 5 | 71 | 88 | LCOM4>=4 | **P3** (2) |
| C | `actions/click_back.py` | 62 | 3 | 0 | 1.00 | 2 | 79 | 93 | dead,params>4 | **P3** (2) |
| C | `actions/click_main_tab.py` | 62 | 3 | 0 | 1.00 | 2 | 79 | 93 | dead,params>4 | **P3** (2) |
| C | `actions/type_message.py` | 62 | 3 | 0 | 1.00 | 10 | 72 | 98 | dead,params>4 | **P3** (2) |
| C | `actions/repeat_loop.py` | 39 | 2 | 0 | 1.00 | 2 | 100 | 71 | cov<80,dead | **P3** (2) |
| C | `actions/conditional_skip.py` | 30 | 2 | 0 | 1.00 | 2 | 100 | 61 | cov<80,dead,no-direct-tests | **P3** (2) |
| C | `actions/base_action.py` | 10 | 2 | 19 | 0.10 | 0 | 100 | 100 | hub | **P3** (2) |
| C | `services/people_service.py` | 219 | 2 | 2 | 0.50 | 8 | 48 | 93 | params>4 | **P3** (1) |
| A | `stores/settings_store.py` | 168 | 1 | 1 | 0.50 | 7 | 56 | 81 | dead | **P3** (1) |
| FROZEN | `bridge/context.py` | 126 | 6 | 2 | 0.75 | 4 | 63 | 91 | params>4 | **P3** (1) |
| A | `stores/session_store.py` | 79 | 1 | 1 | 0.50 | 4 | 73 | 83 | dead | **P3** (1) |
| FROZEN | `core/di.py` | 67 | 0 | 2 | 0.00 | 4 | 65 | 100 | dead | **P3** (1) |
| C | `services/history/__init__.py` | 48 | 6 | 0 | 1.00 | 3 | 61 | 100 | params>4,no-direct-tests | **P3** (1) |
| C | `actions/search_users.py` | 41 | 3 | 0 | 1.00 | 3 | 100 | 100 | dead | **P3** (1) |
| B | `backend/action_engine.py` | 33 | 1 | 0 | 1.00 | 2 | 89 | 100 | dead,shim | **P3** (1) |
| C | `services/run/__init__.py` | 22 | 0 | 0 | 0.00 | 3 | 67 | 100 | dead,no-direct-tests | **P3** (1) |
| C | `services/run_service/__init__.py` | 19 | 0 | 0 | 0.00 | 2 | 75 | 100 | dead,no-direct-tests | **P3** (1) |
| C | `services/cdp_service.py` | 120 | 3 | 1 | 0.75 | 10 | 59 | 99 | - | **P3** (0) |
| D | `backend/chat_agent_js.py` | 118 | 0 | 0 | 0.00 | 3 | 73 | 100 | - | **P3** (0) |
| A | `stores/atomic.py` | 82 | 1 | 3 | 0.25 | 5 | 63 | 93 | - | **P3** (0) |
| A | `stores/jsonio.py` | 66 | 0 | 7 | 0.00 | 6 | 81 | 95 | - | **P3** (0) |
| B | `app/bootstrap.py` | 42 | 7 | 1 | 0.88 | 2 | 100 | 100 | - | **P3** (0) |
| D | `backend/logger.py` | 33 | 0 | 1 | 0.00 | 1 | 100 | 100 | - | **P3** (0) |
| C | `actions/find_click_runner.py` | 15 | 1 | 3 | 0.25 | 0 | 100 | 100 | - | **P3** (0) |
| C | `actions/__init__.py` | 15 | 1 | 0 | 1.00 | 0 | 100 | 100 | no-direct-tests | **P3** (0) |
| B | `backend/bridge.py` | 12 | 2 | 1 | 0.67 | 0 | 100 | 100 | shim | **P3** (0) |
| FROZEN | `core/__init__.py` | 11 | 3 | 0 | 1.00 | 0 | 100 | 100 | no-direct-tests | **P3** (0) |
| B | `backend/db_manager.py` | 9 | 1 | 0 | 1.00 | 0 | 100 | 100 | shim | **P3** (0) |
| B | `backend/history_service.py` | 9 | 0 | 0 | 0.00 | 0 | 100 | 100 | shim | **P3** (0) |
| B | `backend/label_store.py` | 9 | 1 | 0 | 1.00 | 0 | 100 | 100 | shim | **P3** (0) |
| FROZEN | `bridge/__init__.py` | 8 | 0 | 0 | 0.00 | 0 | 100 | 100 | no-direct-tests | **P3** (0) |
| A | `stores/__init__.py` | 10 | 1 | 0 | 1.00 | 0 | 100 | 100 | no-direct-tests | **P3** (0) |
| B | `app/__init__.py` | 6 | 0 | 0 | 0.00 | 0 | 100 | 100 | no-direct-tests | **P3** (0) |
| B | `backend/collector.py` | 7 | 1 | 0 | 1.00 | 0 | 100 | 100 | shim | **P3** (0) |
| B | `backend/history_db.py` | 7 | 1 | 0 | 1.00 | 0 | 100 | 100 | shim | **P3** (0) |
| B | `backend/history_models.py` | 6 | 1 | 0 | 1.00 | 0 | 100 | 100 | shim | **P3** (0) |
| C | `services/__init__.py` | 5 | 0 | 0 | 0.00 | 0 | 100 | 100 | no-direct-tests | **P3** (0) |
| B | `backend/history_repo.py` | 5 | 1 | 0 | 1.00 | 0 | 100 | 100 | shim | **P3** (0) |
| B | `backend/media_store.py` | 5 | 1 | 0 | 1.00 | 0 | 100 | 100 | shim | **P3** (0) |
| B | `backend/user_memory.py` | 5 | 1 | 0 | 1.00 | 0 | 100 | 100 | shim | **P3** (0) |
| C | `services/history_service/__init__.py` | 1 | 0 | 0 | 0.00 | 0 | 100 | 100 | no-direct-tests | **P3** (0) |
| D | `backend/__init__.py` | 1 | 0 | 0 | 0.00 | 0 | 100 | 100 | no-direct-tests | **P3** (0) |

### 1.3 Files > 200 SLOC (21)

| File | Area | SLOC | CCmax | MI | Cov | Notes |
|---|---|---|---|---|---|---|
| `stores/history_repo.py` | D | 1070 | 34 | 0 | 93% | LCOM4=8; MI<20,CC>25,SLOC>300,LCOM4>=4,dead,params>4 |
| `services/collector_service.py` | C | 664 | 82 | 12 | 87% | LCOM4=5; MI<20,CC>25,SLOC>300,LCOM4>=4,dup>50L,dead,params>4 |
| `stores/media_store.py` | D | 664 | 32 | 9 | 82% | LCOM4=5; MI<20,CC>25,SLOC>300,LCOM4>=4,dead,params>4 |
| `stores/history_db.py` | D | 605 | 23 | 32 | 89% | LCOM4=6; MI<40,CC>10,SLOC>300,LCOM4>=4,dead |
| `services/undo_service.py` | C | 590 | 34 | 10 | 28% | LCOM4=5; MI<20,CC>25,SLOC>300,cov<60,LCOM4>=4,params>4 |
| `services/db_service.py` | C | 547 | 21 | 15 | 74% | LCOM4=4; MI<20,CC>10,SLOC>300,cov<80,LCOM4>=4 |
| `backend/chat_parser.py` | D | 540 | 130 | 6 | 81% | LCOM4=3; MI<20,CC>25,SLOC>300,dead,params>4 |
| `stores/label_store.py` | D | 472 | 28 | 14 | 76% | LCOM4=8; MI<20,CC>25,SLOC>300,cov<80,LCOM4>=4,dead |
| `bridge/history_bridge.py` | FROZEN | 449 | 12 | 23 | 54% | LCOM4=4; MI<40,CC>10,SLOC>300,cov<60,LCOM4>=4,dup>50L,dead |
| `backend/dom_highlight.py` | D | 428 | 17 | 51 | 95% | CC>10,SLOC>300,dup>50L,dead,params>4 |
| `backend/scroll_parser.py` | D | 411 | 43 | 35 | 92% | LCOM4=4; MI<40,CC>25,SLOC>300,LCOM4>=4,dead,params>4 |
| `backend/message_injector.py` | D | 384 | 14 | 43 | 68% | CC>10,SLOC>300,cov<80,dead,params>4 |
| `backend/history_query.py` | D | 371 | 22 | 28 | 94% | LCOM4=4; MI<40,CC>10,SLOC>300,LCOM4>=4,params>4 |
| `bridge/router.py` | FROZEN | 337 | 10 | 44 | 79% | SLOC>300,cov<80,dup>50L,hub,dead,params>4 |
| `backend/media_handler.py` | C | 298 | 26 | 50 | 90% | LCOM4=1; CC>25,SLOC>200,params>4 |
| `bridge/stack_bridge.py` | FROZEN | 270 | 7 | 40 | 34% | LCOM4=3; MI<40,SLOC>200,cov<60,dup>50L,dead |
| `backend/cdp_client.py` | D | 263 | 13 | 35 | 61% | LCOM4=3; MI<40,CC>10,SLOC>200,cov<80,hub,dead |
| `backend/config_manager.py` | A | 261 | 17 | 42 | 56% | LCOM4=3; P0-bug,CC>10,SLOC>200,cov<60,hub,tests-red(113) |
| `actions/scroll_parse.py` | C | 242 | 18 | 56 | 90% | LCOM4=4; CC>10,SLOC>200,LCOM4>=4,dead,params>4 |
| `stores/user_memory.py` | D | 230 | 14 | 43 | 99% | LCOM4=3; CC>10,SLOC>200,dead |
| `stores/preset_store.py` | A | 204 | 11 | 40 | 90% | LCOM4=3; CC>10,SLOC>200,dead |

### 1.4 Highest coupling

| File | Area | ←Ca | Ce→ | I | Notes |
|---|---|---|---|---|---|
| `backend/cdp_client.py` | D | 22 | 0 | 0.00 | MI<40,CC>10,SLOC>200,cov<80,hub,dead |
| `actions/base_action.py` | C | 19 | 2 | 0.10 | hub |
| `core/events.py` | FROZEN | 18 | 0 | 0.00 | hub,dead |
| `core/result.py` | FROZEN | 10 | 0 | 0.00 | LCOM4>=4,hub,dead |
| `bridge/router.py` | FROZEN | 1 | 14 | 0.93 | SLOC>300,cov<80,dup>50L,hub,dead,params>4 |
| `backend/config_manager.py` | A | 3 | 9 | 0.75 | P0-bug,CC>10,SLOC>200,cov<60,hub,tests-red(113) |
| `backend/dom_probe.py` | D | 7 | 0 | 0.00 | CC>10,dead,params>4 |
| `stores/jsonio.py` | A | 7 | 0 | 0.00 | - |
| `stores/history_db.py` | D | 6 | 1 | 0.14 | MI<40,CC>10,SLOC>300,LCOM4>=4,dead |
| `stores/user_memory.py` | D | 6 | 0 | 0.00 | CC>10,SLOC>200,dead |
| `backend/visual_click.py` | C | 4 | 4 | 0.50 | CC>25,params>4 |
| `services/undo_service.py` | C | 3 | 4 | 0.57 | MI<20,CC>25,SLOC>300,cov<60,LCOM4>=4,params>4 |
| `stores/history_repo.py` | D | 4 | 2 | 0.33 | MI<20,CC>25,SLOC>300,LCOM4>=4,dead,params>4 |
| `bridge/context.py` | FROZEN | 2 | 6 | 0.75 | params>4 |
| `backend/scroll_parser.py` | D | 2 | 5 | 0.71 | MI<40,CC>25,SLOC>300,LCOM4>=4,dead,params>4 |

Most depended-upon: `backend/cdp_client.py` (Ca **22**, Ce 0 → perfectly stable, do not
change its API), `actions/base_action.py` (19), `core/events.py` (18), `core/result.py` (10),
`stores/jsonio.py` (7), `backend/dom_probe.py` (7).
Most dependent: `bridge/router.py` (Ce **14**, frozen), `backend/config_manager.py` (Ce 9),
`app/bootstrap.py` (Ce 7).

### 1.5 God objects (public methods per class)

| File | Area | Class | methods | LOC | LCOM4 | verdict |
|---|---|---|---|---|---|---|
| `stores/history_repo.py` | D | HistoryRepo | 44 | 1136 | 8 | 🔴 split |
| `stores/label_store.py` | D | LabelStore | 38 | 463 | 8 | 🔴 split |
| `services/collector_service.py` | C | Collector | 36 | 701 | 5 | 🔴 split |
| `stores/media_store.py` | D | MediaStore | 33 | 642 | 5 | 🔴 split |
| `bridge/history_bridge.py` | FROZEN | HistoryBridge | 31 | 490 | 4 | 🔴 split |
| `bridge/stack_bridge.py` | FROZEN | StackBridge | 31 | 298 | 3 | 🔴 split |
| `stores/history_db.py` | D | HistoryDB | 30 | 492 | 6 | 🔴 split |
| `services/db_service.py` | C | DbManager | 27 | 502 | 4 | 🔴 split |
| `services/undo_service.py` | C | UndoService | 26 | 544 | 5 | 🔴 split |
| `stores/user_memory.py` | D | UserMemory | 21 | 228 | 3 | 🔴 split |
| `backend/cdp_client.py` | D | CDPClient | 20 | 215 | 3 | 🟡 watch |
| `bridge/people_bridge.py` | FROZEN | PeopleBridge | 20 | 128 | 2 | 🟡 watch |
| `stores/preset_store.py` | A | PresetStore | 20 | 212 | 3 | 🟡 watch |
| `backend/config_manager.py` | A | ConfigManager | 17 | 227 | 3 | 🟡 watch |

Cohesion: of 82 classes with ≥ 2 methods **only 14 are cohesive** (LCOM4 = 1); LCOM\*
(Henderson–Sellers) mean **0.77** (0 = perfect).

### 1.6 Complexity hot spots (CC)

| CC | LOC | File | line | function |
|---|---|---|---|---|
| 130 | 295 | `backend/chat_parser.py` | 358 | sync_conversation |
| 82 | 212 | `services/collector_service.py` | 293 | _tick |
| 43 | 66 | `backend/chat_parser.py` | 155 | verify_private |
| 43 | 192 | `backend/scroll_parser.py` | 298 | collect |
| 35 | 118 | `actions/collect_history.py` | 87 | execute |
| 34 | 73 | `services/undo_service.py` | 209 | migrate_global_history |
| 34 | 169 | `stores/history_repo.py` | 713 | recover_media |
| 33 | 90 | `stores/history_repo.py` | 167 | rename_if_same_conversation |
| 32 | 88 | `stores/media_store.py` | 426 | _fetch_via_network |
| 31 | 92 | `actions/click_user.py` | 87 | execute |
| 31 | 37 | `services/run/coordinator.py` | 89 | _execute_cycle |
| 29 | 112 | `stores/history_repo.py` | 322 | append |
| 28 | 50 | `stores/label_store.py` | 252 | _normalized |
| 27 | 126 | `backend/visual_click.py` | 56 | find_and_click |
| 26 | 137 | `backend/media_handler.py` | 224 | attach_image |

### 1.7 Duplication — worst Python files

| File | duplicated lines | Area |
|---|---|---|
| `bridge/history_bridge.py` | 116 | FROZEN |
| `backend/dom_highlight.py` | 106 | D |
| `bridge/stack_bridge.py` | 66 | FROZEN |
| `services/collector_service.py` | 65 | C |
| `bridge/router.py` | 60 | FROZEN |
| `bridge/context.py` | 49 | FROZEN |
| `bridge/undo_bridge.py` | 43 | FROZEN |
| `stores/media_store.py` | 42 | D |
| `bridge/label_bridge.py` | 34 | FROZEN |
| `stores/label_store.py` | 33 | D |
| `core/events.py` | 32 | FROZEN |
| `actions/scroll_parse.py` | 32 | C |

JS worst: `ui/js/sash-grid.js` 101, `presets-ui.js` 84, `labels.js` 83, `history-store.js` 82,
`stack-dnd.js` 62. Biggest single clone: `backend/dom_highlight.py` 60-line block ×2;
`bridge/router.py` 11-line block ×3; a 9-line block copied across 6 `actions/*` files.

### 1.8 Dead code

* **1 fully unused module:** `backend/preset_store.py` (3 SLOC, Ca 0, **0 % coverage**) — a
  re-export shim nobody imports.
* **201 vulture findings** (134 unused methods, 28 classes, 11 variables, 10 properties,
  9 attributes, 8 functions, 1 import) — ~28 are false positives (`actions/*` classes
  registered by `__init_subclass__`), so **≈ 173 real**.
* **5 findings at 100 % confidence** (safe deletions):
  `backend/cdp_client.py:35` (`exc_type`, `tb`), `services/run/coordinator.py:53`
  (`scroll_parser`), `services/run/hooks.py:68/71/74` (`coordinator`).
* **12 compat re-export shims** in `backend/` (`bridge`, `collector`, `db_manager`,
  `history_db`, `history_models`, `history_repo`, `history_service`, `label_store`,
  `media_store`, `preset_store`, `user_memory`, `action_engine`) — 3–30 code lines each,
  all `# noqa: F401`. They exist only so old `from backend.x import Y` keeps working.
* **pyflakes** (39 warnings) — undefined names: `services/run/coordinator.py:34 BaseAction`,
  `services/run/coordinator.py:42 get_action_class`, `backend/chat_parser.py:78 AppendResult`;
  plus 12 unused imports and 2 star-imports that mask undefined names
  (`backend/history_models.py`, `services/history_service/__init__.py`).

---

## 2. 🐞 Bug inventory

Severity: 🔴 crash / data loss · 🟠 feature broken · 🟡 regression (was working, now not) ·
⚪ hygiene. **Owner** = the area that will fix it (§5).

### 2.1 🔴 Crashes (runtime)

| # | Bug | Evidence | Root cause | Fix | Owner | Tests hit |
|---|---|---|---|---|---|---|
| B1 | `ConfigManager.save()` raises | `backend/config_manager.py:123 AttributeError: 'BookmarkStore' object has no attribute 'save'` (**50**) | `ConfigManager` calls `bookmarks.save()/blocks.save()/session.save()/presets.save()`, but `BookmarkStore` (and `UndoStore`, `LabelsFileStore`) never define `save`/`flush` | add `save()` to `BookmarkStore`, `flush()` to `UndoStore`/`LabelsFileStore` — **additive**, no signature changes | **A** | 50+ |
| B2 | `ConfigManager.get_state/set_state` raises | `config_manager.py:273 / :291 AttributeError: 'UndoStore' object has no attribute 'history'` (**62**) | facade calls `undo.history() / undo.index() / undo.save_state()`; `UndoStore` exposes `get() / set() / push()` | add `history()`, `index()`, `save_state()` delegating to `get/set` | **A** | 62 |
| B3 | loading a stack crashes the run engine | `services/run/coordinator.py:42 NameError: name 'get_action_class' is not defined` (**25**) | `coordinator.py` uses `get_action_class` (and annotates with `BaseAction`) but imports neither; they live in `actions/base_action.py` | add the 2 imports | **C** | 25 |
| B4 | stores built with a path land in the `atomic` slot | `stores/bookmark_store.py:17 AttributeError: 'str' object has no attribute 'get'` (**3**) + `TypeError: stat: path should be string… not AtomicJsonStore` (**16**) | two constructor conventions: `SettingsStore(path, data)`, `SessionStore(path, data)`, `LabelsFileStore(path)` vs `BlockStore/BookmarkStore/UndoStore(atomic, path)`. `ConfigManager` passes **paths positionally** → binds `atomic=<str>` | make the 3 atomic-first stores coerce a `str` first arg to `path` (zero ripple), then optionally unify signatures later | **A** | 19 |
| B5 | pausing an idle run raises | `services/run/state_machine.py:35 ValueError: invalid transition: idle -> paused` | `RunStateMachine.mark_paused()` calls `transition(PAUSED)` unconditionally; `idle → paused` is not in `_ALLOWED` | make `mark_paused()` idempotent when not running (or let `coordinator.pause()` guard on state) | **C** | 1 |

### 2.2 🟠 Broken features

| # | Bug | Evidence | Root cause | Fix | Owner |
|---|---|---|---|---|---|
| B6 | app-level entry API gone | `tests/test_main_entry.py:359/371/402/410 — module 'main' has no attribute '_queue_path' / 'build_container'` (**24**) | `main.py` was reduced to a 39-SLOC launcher; `MainWindow`/`build_container`/`_queue_path` moved to `app/` | re-point the tests at `app.window` / `app.bootstrap` (production `main.py` stays thin) | **B** |
| B7 | Qt object lifetime in tests | `RuntimeError: Signal source has been deleted` (**20**, `test_person_labels.py:251`, `test_people_undo.py:56`) | bridges are created, wired and garbage-collected inside a test; slots outlive the emitter | keep a reference for the test duration (fixture) | **B** |
| B8 | `Bridge.__new__` leaves QObject uninitialised | `RuntimeError: libshiboken: '__init__' method of object's base class (Router) not called` (**37**: `bridge/db_bridge.py:27`, `bridge/layout_bridge.py:57`, `bridge/label_bridge.py:24`) | tests do `br = Bridge.__new__(Bridge)` and hand-inject attributes; the native QObject is never constructed, so `super().__init__(parent)` on a child bridge fails | call `QObject.__init__(br)` before injecting (test-side only — `bridge/*` is frozen) | **B** |
| B9 | WebChannel construction | `app/window.py:121 TypeError: _QWebChannel.__init__() takes N positional arguments but N were given` | PySide6 6.11 signature change (`QWebChannel(parent)` vs legacy call) | pass the argument as `parent=` | **B** |
| B10 | config/DB round-trip edge cases | `IndexError: list index out of range` (`test_archive_delete_undo.py:296`, `test_history_bridge.py:212`) | state assumed non-empty after a delete/undo sequence | guard + test | **C** / **B** |

### 2.3 🟡 Regressions

| # | Regression | Evidence | Impact | Owner |
|---|---|---|---|---|
| B11 | **382 tests / 26 test files deleted** in the `11eb88b` merge | `git ls-tree` diff vs `b33e312`: `test_undo_bridge`(19), `test_collect_history_contract`(42), `test_scroll_parse_contract`(34), `test_base_action_contract`(25), `test_cdp_bridge`(9), `test_db_bridge`(9), `test_label_bridge`(13), `test_layout_bridge`(10), `test_people_bridge`(10), `test_bridge_router_rules`(12), `test_core_{result,events,di}`(25) … only **1** file added | coverage/mutation dropped for `bridge/*`, `services/run/*`, `services/history/*` | **B** |
| B12 | coverage down: `bridge/` 60.9 % lines / **41.2 % branches**, `app/` 49 % / **8.8 %** | coverage report | unknown blast radius on every bridge change | **B** |
| B13 | `services/history/{query,mutate,export}` executed by **2 test files each**, mutation score 0–7 % | mutation report | refactors there are unguarded | **C** (+ **B** for new tests) |
| B14 | facade kept alive for 6 consumers: `ConfigManager` Ce 9, Ca 3, I 0.75, 19 commits of churn | coupling + churn | change ripple | **A** |

### 2.4 ⚪ Import / startup errors

| # | Error | Where | Status |
|---|---|---|---|
| E1 | `ImportError: cannot import name 'DEFAULT_BOOKMARKS' from 'stores.bookmark_store'` | `backend/config_manager.py:31` | ✅ **fixed** (working tree): import `DEFAULT_URLS as DEFAULT_BOOKMARKS`. This one line made **the whole app unimportable** and killed 23 test modules. |
| E2 | `TypeError: object.__init__() takes exactly one argument` at `bridge/router.py:455` | caused by `tests/integration/services/test_run_service_paths.py` | ✅ **fixed** (working tree): the fake `PySide6` is now injected only when real Qt cannot be imported. Killed 13 further modules. |
| E3 | `ImportError: cannot import name 'migrate' from 'stores.migration'` | `tests/test_stores_migration_rollback.py:24` | 🔴 open — stale test: module only exports `migrate_legacy_config` (excluded from runs) |
| E4 | pyflakes undefined names (`get_action_class`, `BaseAction`, `AppendResult`) | `services/run/coordinator.py:34,42`, `backend/chat_parser.py:78` | 🔴 open — all are `NameError`s waiting to fire on the code path |
| E5 | 8 test files hard-code `sys.path.insert(0, "/home/user/Chat-V-bot")` | tests | 🔴 open — makes the suite machine-specific; replace with a `tests/conftest.py` (**B**) |

---

## 3. 🗺️ Dependency map

### 3.1 Package level (internal imports)

| package | Ce → | ← Ca | I |
|---|---|---|---|
| `core` | 0 | 4 | **0.00** ✅ |
| `stores` | 2 | 4 | 0.33 |
| `actions` | 1 | 2 | 0.33 |
| `backend` | 4 | 6 | 0.40 |
| `services` | 4 | 3 | 0.57 |
| `bridge` | 4 | 1 | 0.80 |
| `app` | 4 | 1 | 0.80 |
| `main` | 2 | 0 | 1.00 |

⚠️ `backend → bridge` exists (`backend/bridge.py` re-exports `bridge.router`), i.e. an
upward edge that violates the "arrows flow down only" rule of
`docs/REFACTOR_2026-09-09_DESIGN.md` §2. Retiring that shim is part of **Area B**.

### 3.2 Area level — proven DAG

| from ↓ / to → | A | B | D | C | FROZEN |
|---|---|---|---|---|---|
| **A** (state contract) | 18 | 0 | **0** | **0** | 4 |
| **D** (data layer) | 0 | 0 | 17 | **0** | 0 |
| **C** (runtime) | 1 | 0 | 45 | 30 | 8 |
| **B** (shell+shims+tests) | 2 | 4 | 10 | 3 | 4 |
| **FROZEN** (`core`, `bridge`) | 2 | 0 | 1 | 9 | 26 |

**Layer order (topological): A → D → C → B.** No cycles among A/B/C/D ✅ — verified
programmatically (`/tmp/an/areas3.py`, DFS cycle check). `FROZEN` files are never modified,
so their edges only record what the other areas must keep compatible.

### 3.3 Cross-area edges (all of them — 9 production file pairs outside the 4 areas' interiors)

| from | to | edges | representative | contract |
|---|---|---|---|---|
| C → D | 45 | `actions/*` → `backend/{cdp_client,dom_probe,scroll_parser,person_filter}`, `services/*` → `backend/{chat_parser,history_query,…}` | D freezes every public signature |
| C → A | 1 | `services/undo_service.py` → `backend/config_manager.py` | A only **adds** methods; no signature changes |
| B → D | 10 | `app/bootstrap.py` → `backend/{cdp_client,criteria_engine}`, shims → `stores/*` | D freezes signatures; shims retire in B |
| B → A | 2 | `app/bootstrap.py` → `backend/config_manager.py`, `backend/preset_store.py` → `stores/preset_store.py` | A keeps facade API |
| B → C | 3 | `backend/action_engine.py` → `actions/base_action.py`, `backend/{collector,db_manager}.py` → `services/*` | shims only re-export |
| FROZEN → C/D/A | 12 | `bridge/context.py` → `services/*`, `bridge/router.py` → `stores/preset_store.py` | **bridge is frozen**: C/D/A must keep those signatures or bridge breaks |

**Rule that makes parallel merges safe:** every area may *add* to its own files and
*internally* split them, but **no area may change a public signature of a file it does not
own**. The 12 FROZEN→area edges are the hard constraint, and they are covered by the
`bridge` contract tests in §7.3.

---

## 4. 🏆 Ranked problems (most → least critical)

### 4.1 Scoring formula (transparent, reproducible)

```
score = 10 (module implicated in a P0 crash)
      +  4 (module appears in a failing-test traceback)
      +  6 (MI < 20)   | +2 (MI < 40)
      +  5 (any CC > 25) | +3 (any CC > 10)
      +  3 (SLOC > 300) | +2 (SLOC > 200)
      +  3 (coverage < 60 %) | +1 (coverage < 80 %)
      +  2 (any class LCOM4 ≥ 4)
      +  2 (> 50 duplicated lines)  + 2 (Ca ≥ 10 or Ce ≥ 8)  + 1 (> 4 params)
      +  1 (vulture findings)  + 3 (Ca = 0 and 0 % coverage → unused)
bands: P0 ≥ 14 · P1 9–13 · P2 5–8 · P3 < 5
```
Distribution: **P0 13 · P1 16 · P2 21 · P3 58** (of 108 modules).

### 4.2 Problem ranking (what to fix, in order)

| Rank | Problem | Why it is #N | Modules | Owner |
|---|---|---|---|---|
| 1 | **Stores↔ConfigManager contract is inconsistent** (2 constructor conventions, missing `save/flush/history/index/save_state`) | 124 test failures + the app cannot save settings; every other fix is unverifiable while this is broken | `backend/config_manager.py`, `stores/{undo,bookmark,labels_file,block}_store.py` | **A** |
| 2 | **`services/run/coordinator.py` undefined names** | hard crash every time a stack is loaded — the core product feature | `services/run/coordinator.py` | **C** |
| 3 | **382 tests deleted / suite 19.2 % red** | no safety net ⇒ every refactor below is a gamble; 63/201 commits are already fix-commits | tests/** | **B** |
| 4 | **`HistoryRepo` god object** (44 methods, 1,136 LOC, MI **0.0**, LCOM4 8, `recover_media` CC 34 / 169 LOC / nesting 6) | worst file in the repo; blocks all history work | `stores/history_repo.py` | **D** |
| 5 | **`backend/chat_parser.sync_conversation`** CC **130**, cog 93, 295 LOC, 14 params, MI 6.3 | untestable, unmodifiable; the parser is the data source for everything | `backend/chat_parser.py` | **D** |
| 6 | **`services/collector_service._tick`** CC **82**, 212 LOC, MI 12 | the live-collection loop; every change risks hangs | `services/collector_service.py` | **C** |
| 7 | **`services/undo_service`** CC 34 (`migrate_global_history`), MI 10.2, coverage **27.7 %**, 301 missed statements | undo/redo is user-visible and barely tested | `services/undo_service.py` | **C** |
| 8 | **`services/history/{query,mutate,export}`** — mutation score **0–7 %**, 2 covering test files | refactor targets with no guard | `services/history/*` | **C**+**B** |
| 9 | **`backend/scroll_parser.collect`** CC 44 / 192 LOC + `actions/scroll_parse.__init__` 20 params | second data path into the app | `backend/scroll_parser.py`, `actions/scroll_parse.py` | **D**/**C** |
| 10 | **`bridge/*` coverage 60.9 % / branch 41.2 %** (frozen, so tests must come from outside) | bridges are the JS↔Python contract | tests/** | **B** |
| 11 | **12 compat shims + 1 dead module** (`backend/preset_store.py` 0 % cov) | dead weight that hides the real dependency graph | `backend/*` shims | **B** |
| 12 | **duplication 8.7 % / 9.6 %** — `dom_highlight` 60-line clone, `bridge/router` ×3, 9-line block ×6 in `actions/*`, JS `sash-grid` 101 lines | change-amplification | `backend/dom_highlight.py`, `actions/*`, `ui/js/*` | **D**/**C** |
| 13 | **`stores/media_store` / `label_store` / `history_db`** MI 9–32, LCOM4 5–8, 30 methods each | maintenance cost | `stores/*` | **D** |
| 14 | **`app/` + `main.py`** entry API drift, WebChannel TypeError, 8.8 % branch coverage | startup path untested | `app/*`, `main.py` | **B** |
| 15 | **173 real dead-code findings**, 12 unused imports, 2 masking star-imports | noise + confusion | all | per area |

---

## 5. 🧩 The four areas

Rules that every area obeys:
* **No file is owned by two areas** (verified in §6.1).
* `bridge/*.py` and `core/*.py` are **frozen** — no area edits them.
* Public signatures of *other* areas' files stay untouched; an area may only split its own
  files internally. New APIs needed from another area ⇒ add them in the *calling* area as a
  thin adapter, or schedule a follow-up.
* Every area ships its own tests and must leave the suite no redder than it found it.

---

### 🅰️ AREA A — Boot & state contract
**Branch:** `fix/area-a-state-contract` · **Files:** 12 · **SLOC:** 1,044 · **Fixes:** problems 1, (partly) 12 · **Kills ≈ 116 of 225 error lines (52 %)**

| Why first | It is the only area that unblocks measurement: until `ConfigManager` can save, ~124 tests fail for reasons unrelated to what they test. |
|---|---|

**Files owned**
| File | LOC | SLOC | Ce→ | ←Ca | CCmax | MI | Cov% | Issues | Pri |
|---|---|---|---|---|---|---|---|---|---|---|
| `backend/config_manager.py` | 313 | 261 | 9 | 3 | 17 | 42 | 56 | P0-bug,CC>10,SLOC>200,cov<60,hub,tests-red(113) | **P0** |
| `stores/bookmark_store.py` | 44 | 34 | 2 | 1 | 4 | 63 | 80 | P0-bug,tests-red(3) | **P0** |
| `stores/block_store.py` | 62 | 48 | 2 | 1 | 8 | 58 | 72 | P0-bug,cov<80,dead | **P1** |
| `stores/labels_file_store.py` | 60 | 45 | 1 | 1 | 3 | 87 | 97 | P0-bug,dead | **P1** |
| `stores/undo_store.py` | 57 | 45 | 2 | 1 | 4 | 60 | 76 | P0-bug,cov<80 | **P1** |
| `stores/preset_store.py` | 244 | 204 | 1 | 3 | 11 | 40 | 90 | CC>10,SLOC>200,dead | **P2** |
| `stores/migration.py` | 117 | 86 | 1 | 1 | 20 | 72 | 92 | CC>10 | **P3** |
| `stores/session_store.py` | 79 | 60 | 1 | 1 | 4 | 73 | 83 | dead | **P3** |
| `stores/settings_store.py` | 168 | 141 | 1 | 1 | 7 | 56 | 81 | dead | **P3** |
| `stores/__init__.py` | 10 | 7 | 1 | 0 | 0 | 100 | 100 | no-direct-tests | **P3** |
| `stores/atomic.py` | 82 | 65 | 1 | 3 | 5 | 63 | 93 | - | **P3** |
| `stores/jsonio.py` | 66 | 48 | 0 | 7 | 6 | 81 | 95 | - | **P3** |

**Scope**

1. **A1** — unify how config stores are constructed. Primary fix (**zero ripple**): in
   `BlockStore`, `BookmarkStore`, `UndoStore` coerce a `str` first argument into `path`
   (`if isinstance(atomic, str): path, atomic = atomic, None`). Optional follow-up (after B
   updates the tests): single signature `Store(path=None, *, atomic=None)` for all 7.
2. **A2** — complete the store API the facade already calls: `BookmarkStore.save()`,
   `UndoStore.history() / index() / save_state() / flush()`, `LabelsFileStore.flush()`.
   All **additive**; `get/set/push/reload/save` keep working.
3. **A3** — make `stores/atomic.py` + `stores/jsonio.py` the single write path (atomic
   tmp+rename) for all 7 stores; no store writes JSON itself.
4. **A4** — contract tests: round-trip, `save()` idempotent, corrupt file isolation,
   concurrent reopen, `migrate_legacy_config` rollback.

**Exit criteria**

`pytest tests/unit/backend/test_config_manager.py tests/unit/backend/test_config_manager_contract.py tests/test_stores_*.py` → **0 failures**
(and the rest of the suite no redder). `python -c "from backend.config_manager import ConfigManager; c=ConfigManager(); c.set('a.b',1); c.save(); print(c.get('a.b'))"` works.

**Risks** — `stores/preset_store.py` is imported by `bridge/router.py` (frozen): keep
`PresetStore(config=..., path=...)` signature. Do not touch `bridge/*`.

---

### 🅳 AREA D — Data & parsing layer
**Branch:** `refactor/area-d-data-layer` · **Files:** 19 · **SLOC:** 6,188 · **Fixes:** problems 4, 5, 9, 12, 13

**Files owned**
| File | LOC | SLOC | Ce→ | ←Ca | CCmax | MI | Cov% | Issues | Pri |
|---|---|---|---|---|---|---|---|---|---|---|
| `stores/history_repo.py` | 1230 | 1070 | 2 | 4 | 34 | 0 | 93 | MI<20,CC>25,SLOC>300,LCOM4>=4,dead,params>4 | **P0** |
| `stores/label_store.py` | 555 | 472 | 0 | 2 | 28 | 14 | 76 | MI<20,CC>25,SLOC>300,cov<80,LCOM4>=4,dead | **P0** |
| `stores/media_store.py` | 750 | 664 | 1 | 2 | 32 | 9 | 82 | MI<20,CC>25,SLOC>300,LCOM4>=4,dead,params>4 | **P0** |
| `backend/chat_parser.py` | 652 | 540 | 2 | 3 | 130 | 6 | 81 | MI<20,CC>25,SLOC>300,dead,params>4 | **P0** |
| `backend/scroll_parser.py` | 495 | 411 | 5 | 2 | 43 | 35 | 92 | MI<40,CC>25,SLOC>300,LCOM4>=4,dead,params>4 | **P0** |
| `backend/cdp_client.py` | 311 | 263 | 0 | 22 | 13 | 35 | 61 | MI<40,CC>10,SLOC>200,cov<80,hub,dead | **P1** |
| `backend/history_query.py` | 420 | 371 | 1 | 2 | 22 | 28 | 94 | MI<40,CC>10,SLOC>300,LCOM4>=4,params>4 | **P1** |
| `stores/history_db.py` | 757 | 605 | 1 | 6 | 23 | 32 | 89 | MI<40,CC>10,SLOC>300,LCOM4>=4,dead | **P1** |
| `backend/dom_highlight.py` | 465 | 428 | 1 | 2 | 17 | 51 | 95 | CC>10,SLOC>300,dup>50L,dead,params>4 | **P1** |
| `backend/message_injector.py` | 454 | 384 | 2 | 3 | 14 | 43 | 68 | CC>10,SLOC>300,cov<80,dead,params>4 | **P1** |
| `stores/history_models.py` | 196 | 149 | 0 | 4 | 15 | 56 | 100 | CC>10,LCOM4>=4,dead,params>4 | **P2** |
| `stores/user_memory.py` | 266 | 230 | 0 | 6 | 14 | 43 | 99 | CC>10,SLOC>200,dead | **P2** |
| `backend/dom_probe.py` | 217 | 199 | 0 | 7 | 14 | 65 | 98 | CC>10,dead,params>4 | **P2** |
| `backend/criteria_engine.py` | 102 | 87 | 0 | 2 | 7 | 58 | 99 | LCOM4>=4,dead | **P3** |
| `backend/tab_matcher.py` | 130 | 102 | 0 | 1 | 20 | 56 | 92 | CC>10 | **P3** |
| `backend/person_filter.py` | 132 | 104 | 0 | 3 | 10 | 62 | 98 | dead,params>4 | **P3** |
| `backend/__init__.py` | 1 | 0 | 0 | 0 | 0 | 100 | 100 | no-direct-tests | **P3** |
| `backend/chat_agent_js.py` | 118 | 84 | 0 | 0 | 3 | 73 | 100 | - | **P3** |
| `backend/logger.py` | 33 | 25 | 0 | 1 | 1 | 100 | 100 | - | **P3** |

**Scope**

1. **D1** — split `HistoryRepo` (44 methods / 1,136 LOC / LCOM4 8) into
   `history_repo/{write,read,media,maintenance}.py` behind the same class name (facade
   re-exporting the parts) — **no caller changes**.
2. **D2** — decompose `chat_parser.sync_conversation` (CC 130 → target ≤ 15) into
   `normalize → diff → align → emit`; extract `verify_private` (CC 43).
3. **D3** — `scroll_parser.collect` (CC 44 / 192 LOC) → state-machine + helpers;
   `history_db._rebuild_legacy_messages` (CC 23).
4. **D4** — kill the biggest clones: `dom_highlight` 60-line block ×2 (extract
   `build_probe_variant`), `backend/js/chat_agent.js` `selectPane` (CC 30) / `visiblePane`
   (CC 20).
5. **D5** — split `MediaStore` (33 methods), `LabelStore` (38), `HistoryDB` (30) by
   responsibility; add the missing `Result[T]` error paths.

**Exit criteria** — `radon cc` on owned files: 0 functions > CC 25, ≤ 5 > CC 10; every owned
file MI ≥ 20; duplication inside owned files < 4 %; coverage of owned files ≥ 85 % lines /
75 % branches; `pytest tests/test_history_repo*.py tests/test_media_store*.py
tests/test_chat_parser*.py tests/test_scroll_parse_pipeline.py tests/test_label_store*.py
tests/test_history_db*.py tests/test_private_gate.py` green.

**Risks** — `backend/cdp_client.py` (Ca 22) and `stores/user_memory.py` (Ca 6) are widely
depended upon: **internal changes only**, signatures frozen. `backend/criteria_engine.py`
and `person_filter.py` are covered by contract tests in `tests/unit/backend/` (owned by A/B
for those files? — no: the *tests* are owned by **B**; D may add new tests under
`tests/unit/backend/` only for D-owned modules).

---

### 🅲 AREA C — Runtime: actions, services, automation helpers
**Branch:** `refactor/area-c-runtime` · **Files:** 43 · **SLOC:** 5,397 · **Fixes:** problems 2, 6, 7, 8, 9, 12

**Files owned**
| File | LOC | SLOC | Ce→ | ←Ca | CCmax | MI | Cov% | Issues | Pri |
|---|---|---|---|---|---|---|---|---|---|---|
| `services/run/coordinator.py` | 127 | 120 | 5 | 0 | 31 | 21 | 95 | P0-bug,MI<40,CC>25,dead,params>4,tests-red(25),no-direct-tests | **P0** |
| `services/collector_service.py` | 776 | 664 | 4 | 2 | 82 | 12 | 87 | MI<20,CC>25,SLOC>300,LCOM4>=4,dup>50L,dead,params>4 | **P0** |
| `services/undo_service.py` | 661 | 590 | 4 | 3 | 34 | 10 | 28 | MI<20,CC>25,SLOC>300,cov<60,LCOM4>=4,params>4 | **P0** |
| `services/db_service.py` | 612 | 547 | 0 | 2 | 21 | 15 | 74 | MI<20,CC>10,SLOC>300,cov<80,LCOM4>=4 | **P0** |
| `services/history/export.py` | 153 | 137 | 1 | 0 | 25 | 16 | 80 | MI<20,CC>10,cov<80,dead,no-direct-tests | **P1** |
| `services/history/mutate.py` | 177 | 162 | 0 | 0 | 19 | 19 | 73 | MI<20,CC>10,cov<80,dead,no-direct-tests | **P1** |
| `actions/scroll_parse.py` | 283 | 242 | 4 | 0 | 18 | 56 | 90 | CC>10,SLOC>200,LCOM4>=4,dead,params>4 | **P1** |
| `services/run/progress.py` | 181 | 158 | 3 | 0 | 14 | 19 | 87 | MI<20,CC>10,no-direct-tests | **P1** |
| `actions/collect_history.py` | 204 | 176 | 3 | 0 | 35 | 48 | 78 | CC>25,cov<80,dead,params>4 | **P2** |
| `backend/media_handler.py` | 360 | 298 | 3 | 1 | 26 | 50 | 90 | CC>25,SLOC>200,params>4 | **P2** |
| `services/history/query.py` | 155 | 133 | 0 | 0 | 11 | 28 | 88 | MI<40,CC>10,LCOM4>=4,dead,no-direct-tests | **P2** |
| `actions/click_user.py` | 209 | 170 | 3 | 0 | 31 | 52 | 85 | CC>25,dead,params>4 | **P2** |
| `actions/wait_page.py` | 82 | 72 | 3 | 0 | 18 | 58 | 22 | CC>10,cov<60,dead,no-direct-tests | **P2** |
| `backend/visual_click.py` | 187 | 151 | 4 | 4 | 27 | 57 | 91 | CC>25,params>4 | **P2** |
| `services/run/error_recovery.py` | 179 | 162 | 1 | 0 | 15 | 26 | 83 | MI<40,CC>10,params>4,no-direct-tests | **P2** |
| `actions/click_send.py` | 81 | 69 | 4 | 0 | 4 | 73 | 35 | cov<60,dead,params>4,no-direct-tests | **P2** |
| `actions/mark_messaged.py` | 86 | 75 | 2 | 0 | 16 | 70 | 76 | CC>10,cov<80,dead | **P2** |
| `actions/take_person.py` | 91 | 73 | 2 | 0 | 12 | 76 | 79 | CC>10,cov<80,dead | **P2** |
| `services/layout_service.py` | 203 | 175 | 0 | 3 | 19 | 42 | 98 | CC>10,LCOM4>=4 | **P2** |
| `services/run/hooks.py` | 151 | 125 | 0 | 0 | 8 | 32 | 95 | MI<40,LCOM4>=4,dead,no-direct-tests | **P2** |
| `actions/pause.py` | 33 | 26 | 2 | 0 | 3 | 75 | 46 | cov<60,dead,no-direct-tests | **P3** |
| `services/run/state_machine.py` | 68 | 53 | 0 | 0 | 3 | 49 | 88 | tests-red(1),no-direct-tests | **P3** |
| `actions/context.py` | 78 | 50 | 0 | 0 | 4 | 85 | 87 | LCOM4>=4,dead | **P3** |
| `actions/registry.py` | 109 | 80 | 0 | 3 | 7 | 70 | 100 | LCOM4>=4,dead | **P3** |
| `actions/attach_image.py` | 82 | 73 | 3 | 0 | 4 | 80 | 88 | dead,params>4 | **P3** |
| `actions/base.py` | 92 | 71 | 1 | 1 | 5 | 71 | 88 | LCOM4>=4 | **P3** |
| `actions/base_action.py` | 10 | 8 | 2 | 19 | 0 | 100 | 100 | hub | **P3** |
| `actions/click_back.py` | 62 | 54 | 3 | 0 | 2 | 79 | 93 | dead,params>4 | **P3** |
| `actions/click_main_tab.py` | 62 | 54 | 3 | 0 | 2 | 79 | 93 | dead,params>4 | **P3** |
| `actions/conditional_skip.py` | 30 | 23 | 2 | 0 | 2 | 100 | 61 | cov<80,dead,no-direct-tests | **P3** |
| `actions/custom_find.py` | 109 | 97 | 4 | 0 | 8 | 74 | 96 | dead,params>4 | **P3** |
| `actions/repeat_loop.py` | 39 | 30 | 2 | 0 | 2 | 100 | 71 | cov<80,dead | **P3** |
| `actions/type_message.py` | 62 | 52 | 3 | 0 | 10 | 72 | 98 | dead,params>4 | **P3** |
| `actions/search_users.py` | 41 | 33 | 3 | 0 | 3 | 100 | 100 | dead | **P3** |
| `services/history/__init__.py` | 48 | 41 | 6 | 0 | 3 | 61 | 100 | params>4,no-direct-tests | **P3** |
| `services/people_service.py` | 219 | 187 | 2 | 2 | 8 | 48 | 93 | params>4 | **P3** |
| `services/run/__init__.py` | 22 | 19 | 0 | 0 | 3 | 67 | 100 | dead,no-direct-tests | **P3** |
| `services/run_service/__init__.py` | 19 | 16 | 0 | 0 | 2 | 75 | 100 | dead,no-direct-tests | **P3** |
| `actions/__init__.py` | 15 | 11 | 1 | 0 | 0 | 100 | 100 | no-direct-tests | **P3** |
| `actions/find_click_runner.py` | 15 | 12 | 1 | 3 | 0 | 100 | 100 | - | **P3** |
| `services/__init__.py` | 5 | 4 | 0 | 0 | 0 | 100 | 100 | no-direct-tests | **P3** |
| `services/cdp_service.py` | 120 | 103 | 3 | 1 | 10 | 59 | 99 | - | **P3** |
| `services/history_service/__init__.py` | 1 | 1 | 0 | 0 | 0 | 100 | 100 | no-direct-tests | **P3** |

**Scope**

1. **C1** — **P0 crash**: import `get_action_class` / `BaseAction` in
   `services/run/coordinator.py` (B3); make `RunStateMachine.mark_paused()` idempotent (B5).
2. **C2** — decompose `Collector._tick` (CC 82 / 212 LOC) into
   `_tick_probe / _tick_parse / _tick_persist / _tick_schedule`; extract the 5 duplicated
   lines at `collector_service.py:723-729`.
3. **C3** — `UndoService` (MI 10.2, cov 27.7 %): split `migrate_global_history`
   (CC 34, nesting 6), raise coverage to ≥ 80 % with real undo/redo round-trips.
4. **C4** — parameter objects for the 20/19/13/12-param constructors
   (`actions/scroll_parse`, `actions/click_user`, `actions/custom_find`,
   `backend/visual_click.find_and_click`).
5. **C5** — test the orphaned modules: `services/history/{query,mutate,export}` and
   `services/run/{state_machine,progress}` — target mutation ≥ 70 %.
6. **C6** — dedupe the 9-line block shared by 6 `actions/*` files into
   `actions/find_click_runner.py` (already the shared helper).

**Exit criteria** — 0 undefined names (`pyflakes` clean on owned files); CC ≤ 25 max, ≤ 3
functions > CC 15; `services/*` mean MI ≥ 55; coverage of owned files ≥ 85 % / branches
≥ 75 %; mutation ≥ 70 % on `services/run/*` + `services/history/*`;
`pytest tests/test_engine_standalone_run.py tests/test_action_engine_sequence.py
tests/test_collector_state.py tests/integration/services/ tests/test_take_person.py
tests/test_click_user_order.py tests/test_history_query*.py` green.

**Risks** — `services/undo_service.py` imports `backend/config_manager.py` (Area A): use the
existing facade API only; if a new accessor is needed, add it **in Area A's follow-up**, not
here. Bridge calls services through `bridge/context.py` (frozen) — keep service
constructors' signatures.

---

### 🅱️ AREA B — Shell, compat shims & the test suite
**Branch:** `test/area-b-safety-net` · **Prod. files:** 17 (+ all of `tests/**`) · **SLOC:** 330 ·
**Fixes:** problems 3, 10, 11, 14 · **Split into two PRs** (B1 merges right after A, B2 last)

**Files owned**
| File | LOC | SLOC | Ce→ | ←Ca | CCmax | MI | Cov% | Issues | Pri |
|---|---|---|---|---|---|---|---|---|---|---|
| `app/window.py` | 128 | 110 | 0 | 1 | 6 | 34 | 42 | P0-bug,MI<40,cov<60,dead,tests-red(1) | **P0** |
| `main.py` | 49 | 39 | 4 | 0 | 2 | 60 | 78 | P0-bug,cov<80,no-direct-tests | **P1** |
| `backend/preset_store.py` | 5 | 3 | 1 | 0 | 0 | 100 | 0 | cov<60,shim,UNUSED | **P2** |
| `app/lifecycle.py` | 62 | 54 | 0 | 1 | 9 | 52 | 16 | cov<60,params>4 | **P3** |
| `backend/action_engine.py` | 33 | 29 | 1 | 0 | 2 | 89 | 100 | dead,shim | **P3** |
| `app/__init__.py` | 6 | 5 | 0 | 0 | 0 | 100 | 100 | no-direct-tests | **P3** |
| `app/bootstrap.py` | 42 | 36 | 7 | 1 | 2 | 100 | 100 | - | **P3** |
| `backend/bridge.py` | 12 | 9 | 2 | 1 | 0 | 100 | 100 | shim | **P3** |
| `backend/collector.py` | 7 | 5 | 1 | 0 | 0 | 100 | 100 | shim | **P3** |
| `backend/db_manager.py` | 9 | 7 | 1 | 0 | 0 | 100 | 100 | shim | **P3** |
| `backend/history_db.py` | 7 | 5 | 1 | 0 | 0 | 100 | 100 | shim | **P3** |
| `backend/history_models.py` | 6 | 5 | 1 | 0 | 0 | 100 | 100 | shim | **P3** |
| `backend/history_repo.py` | 5 | 3 | 1 | 0 | 0 | 100 | 100 | shim | **P3** |
| `backend/history_service.py` | 9 | 7 | 0 | 0 | 0 | 100 | 100 | shim | **P3** |
| `backend/label_store.py` | 9 | 7 | 1 | 0 | 0 | 100 | 100 | shim | **P3** |
| `backend/media_store.py` | 5 | 3 | 1 | 0 | 0 | 100 | 100 | shim | **P3** |
| `backend/user_memory.py` | 5 | 3 | 1 | 0 | 0 | 100 | 100 | shim | **P3** |

**B1 — harness hygiene (merge right after A)**
1. `tests/conftest.py` (new): insert the repo root on `sys.path` once; delete the 8
   hard-coded `/home/user/Chat-V-bot` insertions.
2. Fix `Bridge.__new__` tests → `QObject.__init__(br)` (B8), keep bridge refs alive (B7).
3. `app/window.py` QWebChannel keyword fix (B9); port `test_main_entry.py` to the `app/*`
   API (B6); delete/repair `tests/test_stores_migration_rollback.py` (E3).
4. Retire the **12 compat shims** (`backend/{bridge,collector,db_manager,history_db,
   history_models,history_repo,history_service,label_store,media_store,preset_store,
   user_memory,action_engine}.py`) once no test imports them — `backend/preset_store.py`
   can go immediately (0 importers, 0 % coverage).

**B2 — restore the safety net (merge last)**
5. Re-add the **382 deleted tests**, rewritten against today's layout:
   `tests/unit/bridge/` (9 module tests), `tests/unit/actions/` (10 block contract tests),
   `tests/unit/core/` (result/events/di were deleted → keep the `tests/unit/core/*` versions
   and extend), and the run-engine contract tests.
6. New tests for the two weakest spots: `bridge/*` (branch 41 % → ≥ 75 %) and `app/*`
   (branch 8.8 % → ≥ 60 %).
7. JS: keep the 22 node test files green; add DOM-less unit tests for
   `ui/js/{sash-grid,labels,presets-ui}.js` (top duplication).

**Exit criteria** — `pytest tests -q` → **0 failures**; line ≥ 85 %, branch ≥ 78 %;
`node tests/*.js` green; no test hard-codes an absolute path; `pyflakes tests` clean.

**Risks** — B2 touches the most files; keep it to **test files only** so it can never
conflict with A/C/D. If a restored test needs a production change, file it against the
owning area instead.

---

## 6. ✅ Independence proof

### 6.1 File ownership — disjoint by construction

| check | result |
|---|---|
| every production file assigned to exactly one area | ✅ 108 / 108 (A 12 · B 17 · C 43 · D 19 · frozen 17) |
| files assigned to two areas | ✅ **0** (asserted programmatically in `/tmp/an/areas3.py`) |
| `bridge/*.py` in any area | ✅ **no** (12 files frozen, as required) |
| `core/*.py` in any area | ✅ **no** (5 files frozen — clean, MI 87, 100 % covered) |
| test files in any production area | ✅ **no** — all `tests/**` belong to B |

### 6.2 Dependency direction (topological order A → D → C → B)

* **A** imports **nothing** from C or D (its only outward edges are to `core`, frozen).
* **D** imports **nothing** from A, B or C.
* **C** imports from A (1 edge) and D (45) — both lower layers.
* **B** imports from A (2), C (3), D (10) — all lower layers.
* Cycle check over {A,B,C,D}: **ACYCLIC ✅**.

### 6.3 API-freeze contracts (what each area promises the others)

| Area | Freezes | Consumed by |
|---|---|---|
| A | `ConfigManager` public surface (`get/set/get_copy/save/load/get_state/set_state/named_*/validate/DEFAULTS/MAX_STACK_HISTORY/_path`), `PresetStore(config=, path=)` | `services/undo_service.py` (C), `app/bootstrap.py` + `bridge/undo_bridge.py` (B/frozen) |
| D | `CDPClient`, `CriteriaEngine`, `PersonFilter`, `ScrollParser`, `chat_parser` public functions, `stores/{history_repo,history_db,media_store,label_store,user_memory}` public methods | all of C, `app/bootstrap.py`, `bridge/context.py` |
| C | `services/*` public methods (esp. `Collector`, `UndoService`, `DbManager`, `CdpService`, `PeopleService`, `LayoutService`), `actions/*` block classes, `ActionRegistry` API | `bridge/context.py` (frozen, 9 edges), `app/bootstrap.py` |
| B | `main()` entry, `app.bootstrap/lifecycle/window` API | nothing (top layer) |

### 6.4 Conflict risk

| pair | shared files | risk |
|---|---|---|
| A ↔ B | none (tests are B's) | 🟢 low — but A's store-signature unification needs B to update tests ⇒ ship A1 as a *coercion* (no signature change) to stay independent |
| A ↔ C | none | 🟢 low — C uses the existing facade API |
| A ↔ D | none | 🟢 low |
| C ↔ D | none | 🟡 medium — 45 import edges; D must not rename/move anything C imports |
| B ↔ C/D | none | 🟡 medium — B's restored tests will encode C/D behaviour; land B2 **last** |

---

## 7. 🔀 Merge plan

### 7.1 Order

```
        ┌──────────────────────────────────────────────┐
        │ 0.  hotfix (already in working tree)         │  E1 + E2  → app imports again
        └───────────────────┬──────────────────────────┘
                            ▼
        ┌──────────────────────────────────────────────┐
        │ 1.  AREA A   fix/area-a-state-contract       │  unblocks measurement
        └───────────────────┬──────────────────────────┘
                            ▼
        ┌───────────────┬───────────────┬──────────────┐
        │ 2a. AREA D    │ 2b. AREA C    │ 2c. B1       │   parallel (independent)
        │ data layer    │ runtime       │ harness      │
        └───────────────┴───────┬───────┴──────────────┘
                                ▼
        ┌──────────────────────────────────────────────┐
        │ 3.  B2  restore 382 tests + new coverage     │
        └───────────────────┬──────────────────────────┘
                            ▼
        ┌──────────────────────────────────────────────┐
        │ 4.  final cleanup PR (§7.4)                  │
        └──────────────────────────────────────────────┘
```
D before C is *preferred* (C depends on D's signatures) but parallel is safe **because no
file overlaps and D freezes its public API**. If C needs a new D API, C adds a local adapter
and the API moves in the cleanup PR.

### 7.2 Gate for every merge

1. `pytest tests -q` — failures **must not increase** vs the pre-merge baseline
   (baseline today: 314).
2. `python -m pyflakes core actions backend bridge services stores app main.py` — 0 new warnings.
3. `python -c "import backend.bridge, app.bootstrap, main"` — imports clean.
4. Coverage of the *touched* files: lines ≥ 85 %, branches ≥ 75 % (or a written exception).
5. `radon cc` on touched files: no function > CC 25, no new function > CC 10.
6. `node tests/*.js` green (if `ui/js` or `backend/js` changed).
7. PR template must list: files touched (must match this doc's ownership), API changes
   (must be **additive only**), new tests, metric delta.

### 7.3 Integration test checklist (run after B2, before release)

**A. Static**
- [ ] `pytest tests -q` → **0 failed**, ≥ 1,900 tests collected
- [ ] `pytest --cov=… --cov-branch` → line ≥ 85 %, branch ≥ 78 %
- [ ] mutation sample (17 modules) ≥ 70 %
- [ ] `radon mi` → no file in rank C, ≤ 3 in rank B
- [ ] `vulture --min-confidence 90` → 0 findings; `--min-confidence 60` → < 40
- [ ] clone detection → py < 5 %, js < 6 %
- [ ] `pyflakes` clean on production + tests

**B. Behavioural (headless `QT_QPA_PLATFORM=offscreen`)**
- [ ] `python main.py` boots, window builds, WebChannel registers, no traceback
- [ ] `Bridge` (router) exposes **every** domain signal/slot — `tests/test_bridge_router.py` parity test
- [ ] config migration: legacy `config.json` → `config/*.json`, then `ConfigManager.save()` round-trip, then reopen
- [ ] undo/redo across stack + grid + people on one timeline (the U1–U11 scenarios from the deleted `test_undo_bridge.py`)
- [ ] DB world switch (`switch_db`) + media back-fill + `recover_media` on a corrupted DB
- [ ] run engine: load a 6-block stack → run → pause → resume → stop; `RunStateMachine` never raises
- [ ] collector: 3 tick cycles against the JS stub, no duplicate rows
- [ ] JS: `node tests/*.js` (22 files) green; `tests/dom_stub.js` harness still matches the real DOM contract
- [ ] attach-image dialog + media paths with a temp `saved_media/`

**C. Non-regression on the numbers that matter**
- [ ] `backend/cdp_client.py` (Ca 22) and `actions/base_action.py` (Ca 19) byte-identical public API
- [ ] `bridge/*` untouched (`git diff --stat origin/main -- bridge/` empty)
- [ ] `core/*` untouched

### 7.4 Final cleanup PR

* Move `get_action_class`/`BaseAction` re-exports behind one module if both C and B need them.
* Delete the 12 compat shims once `grep -r "from backend\." --include=*.py .` is clean.
* Remove `services/run_service/__init__.py` and `services/history_service/__init__.py`
  (empty packages kept only for old import paths).
* Re-run the whole measurement and publish
  `reports/CODE_QUALITY_METRICS_2026-09-XX.md` with the new numbers.
* Add CI: `pytest --cov --cov-fail-under=85`, `radon cc -nc`, `vulture --min-confidence 90`,
  `pyflakes`, `node tests/*.js`.

---

## 8. Effort & risk

| Area | Effort | Risk | Notes |
|---|---|---|---|
| A | 0.5–1 d | 🟢 low | additive API + coercion; no signature changes |
| D | 4–6 d | 🟡 medium | biggest files; needs the D5 tests written *before* splitting |
| C | 4–6 d | 🟡 medium | 43 files; the P0 crash import can ship as a 2-line PR on its own |
| B1 | 1 d | 🟢 low | test-only + 1 QWebChannel fix |
| B2 | 3–5 d | 🟡 medium | restoring 382 tests is the highest-value, lowest-risk work here |
| cleanup | 0.5 d | 🟢 low | after all merges |

**Biggest risk:** D renaming something C imports. Mitigation — D's PR must include
`grep -rn "<symbol>" <other areas>` evidence, and the integration checklist has an explicit
"bridge untouched / public API identical" gate.

---

## 9. Appendix — reproduction

```bash
# env (headless Qt)
python3 -m venv .metrics-venv && .metrics-venv/bin/pip install \
    radon lizard coverage pytest pytest-timeout pytest-cov vulture pyflakes \
    PySide6 aiosqlite aiohttp websockets qasync
python3 tools/build_stubs.py .metrics-venv /tmp/stublibs      # headless Qt stub libs
export LD_LIBRARY_PATH=/tmp/stublibs QT_QPA_PLATFORM=offscreen

# suite + coverage
.metrics-venv/bin/python -m pytest tests -q --timeout=120 \
  --cov=core --cov=actions --cov=backend --cov=bridge --cov=services --cov=stores \
  --cov=app --cov=main --cov-branch

# static
.metrics-venv/bin/python -m pyflakes core actions backend bridge services stores app main.py
.metrics-venv/bin/vulture core actions backend bridge services stores app main.py --min-confidence 90
.metrics-venv/bin/radon cc -s -a core actions backend bridge services stores app main.py
.metrics-venv/bin/lizard ui/js backend/js bridge -l javascript
```
Analysis scripts used for this doc (regenerate any number in it):
per-module scan `/tmp/an/scan.py`, MI + duplication + dead code `/tmp/an/extra.py`,
area assignment + DAG `/tmp/an/areas3.py`, ranking + tables `/tmp/an/tables.py`.
