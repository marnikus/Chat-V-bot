# 📊 Code Quality Metrics — Chat-V-bot @ `arena/01a08724-chat-v-bot`

**Date:** 2026-09-09 · **Measured commit:** `392fdff` + hotfix `032ae5f`
**Scope:** `core/ actions/ backend/ bridge/ services/ stores/ app/ main.py` (108 files,
18,250 LOC / 13,852 SLOC) + `ui/js/ backend/js/ bridge/*.js` (23 files, 8,455 SLOC)
**Test scope:** 95 Python test files (19,413 SLOC) + 22 JS test files (6,295 SLOC)
**Framework:** the threshold table you supplied (CC ≤ 10, cognitive ≤ 15, nesting ≤ 3–4,
function ≤ 20–30 LOC, class ≤ 200–300 LOC, ≤ 3–4 params, ≤ 10–15 methods/class,
coverage ≥ 80 %, branch ≥ 75 %, mutation ≥ 70 %, test:code ≈ 1:1, LCOM → 0, I → 0)

---

## 0. TL;DR scoreboard

| # | Metric | Threshold | Measured now | Verdict |
|---|---|---|---|---|
| 1 | Cyclomatic complexity / function | ≤ 10 | median 2 · **75 / 1,031 over (7.3 %)** · max 130 | 🟡 |
| 2 | Cognitive complexity / function | ≤ 15 | median 1 · **28 over (2.7 %)** · max 93 | 🟢 |
| 3 | Max nesting depth | ≤ 3–4 | **8 functions over 4** (max 8) | 🟢 |
| 4 | Function length | ≤ 20–30 LOC | median 7 · **83 over 30 (8.0 %)** · max 295 | 🟡 |
| 5 | Class length | ≤ 200–300 | **10 classes over 300 LOC** (max 1,136) | 🔴 |
| 6 | Parameters / function | ≤ 3–4 | **47 over 4** (max 20) | 🟡 |
| 7 | Methods / class | ≤ 10–15 | **15 classes over 15 methods** (max 44) | 🔴 |
| 8 | Afferent/efferent coupling | keep low | `backend.cdp_client` Ca=22, `bridge.router` Ce=14 | 🟡 |
| 9 | Instability I = Ce/(Ca+Ce) | → 0 | `core` 0.00 ✅ · `app`/`bridge` 0.80 🔴 · `services` 0.57 | 🟡 |
| 10 | LCOM (cohesion) | → 0 | **only 14 / 82 classes are cohesive (LCOM4 = 1)**; LCOM\* mean 0.77 | 🔴 |
| 11 | Line coverage | ≥ 80 % | **77.17 %** | 🟡 |
| 12 | Branch coverage | ≥ 75 % | **68.85 %** | 🔴 |
| 13 | Mutation score | ≥ 70 % | **49.6 %** (120/242, 17-module sample) | 🔴 |
| 14 | Test-to-code ratio | ~1:1 | **1.15 : 1** | 🟢 |
| 15 | Suite health | 0 red | **314 / 1,640 tests red (19.2 %)** | 🔴 |
| 16 | Duplicated code | ~0 % | **Python 8.67 % · JS 9.59 %** | 🟡 |
| 17 | Dead code | 0 | **201 vulture findings (7 ≥ 90 % conf.)** + 10 compat shims | 🟡 |
| 18 | Maintainability Index | high | mean **64.0** (A: 100 files, B: 6, **C: 2**) | 🟡 |
| 19 | Code churn | low | **202 commits in 6 days, 63 are fix/revert (31 %)** | 🔴 |
| 20 | Bug density | low | 3.5 fix-commits / KLOC (6-day window) | 🟡 |

**Headline:** the architecture split (`bridge/` package, `services/`, `stores/`, `core/`) is
real and working — `core/` is 100 % covered, MI 87, mutation 93–100 %, and it is the only
package with I = 0.00. What is broken is the **stores ↔ `ConfigManager` contract** and the
**test suite**: the app did not even import at `392fdff`, and 19.2 % of tests are red.

---

## 0.1 🚨 P0 blockers found while measuring (2 fixed by me, 6 left)

| ID | Blocker | Evidence | Status |
|---|---|---|---|
| **P0-1** | `backend/config_manager.py` imported `DEFAULT_BOOKMARKS` from `stores.bookmark_store`; the store defines `DEFAULT_URLS` → **`ImportError` at app start**; 23 test modules could not import | `ImportError: cannot import name 'DEFAULT_BOOKMARKS'` | ✅ **fixed** in `032ae5f` (1 line) |
| **P0-2** | `tests/integration/services/test_run_service_paths.py` injected a **fake `PySide6` into `sys.modules`** unconditionally → every later real-Qt import died; 13 more test modules red | `TypeError: object.__init__() takes exactly one argument` in `bridge/router.py` | ✅ **fixed** in `032ae5f` (stub only when real Qt is missing) |
| **P0-3** | `UndoStore` API mismatch: `config_manager`, `layout_bridge`, `router` call `undo.history()` / `undo.index()`, the store exposes `get()` / `set()` / `push()` | **124 failures** (`'UndoStore' object has no attribute 'history'`) | 🔴 open |
| **P0-4** | `ConfigManager.save()` calls `bookmarks.save()` / `blocks.save()` / `session.save()` / `presets.save()`; `BookmarkStore`, `UndoStore`, `LabelsFileStore` have **no `save()`/`flush()`** | **101 failures** (`'BookmarkStore' object has no attribute 'save'`) | 🔴 open |
| **P0-5** | `services/run/coordinator.py:42` calls `get_action_class(...)` but **never imports it** → `NameError` every time a stack is loaded | **50 failures**, and a real runtime crash | 🔴 open |
| **P0-6** | `main.py` no longer defines `MainWindow`, `build_container`, `_queue_path` (they moved to `app/`); 3 test files still assert the old entry-point API | **46 failures** | 🔴 open |
| **P0-7** | `tests/test_stores_migration_rollback.py` imports `migrate, needs_migration` from `stores.migration`; that module only has `migrate_legacy_config` (stale test) | 1 module cannot be collected (excluded from the run) | 🔴 open |
| **P0-8** | **26 test files / 382 tests deleted** between `b33e312` and HEAD (see §7) | `git ls-tree` diff | 🔴 open |

---

## 1. 🧱 Complexity metrics

### 1.1 Cyclomatic complexity (radon, McCabe) — 1,031 functions

| Statistic | Value |
|---|---|
| median / mean | **2** / 4.2 |
| p90 / max | 9 / **130** |
| over 10 (your limit) | **75 (7.3 %)** |
| over 15 | 35 (3.4 %) |
| over 20 | 20 (1.9 %) |

Worst offenders (the refactor queue):

| CC | Cog | LOC | Nest | Params | Function |
|---|---|---|---|---|---|
| **130** | 93 | 295 | 5 | 14 | `backend/chat_parser.py:358 sync_conversation` |
| **82** | 61 | 212 | 3 | 0 | `services/collector_service.py:293 Collector._tick` |
| **44** | 39 | 192 | 4 | 4 | `backend/scroll_parser.py:298 ScrollParser.collect` |
| 43 | 31 | 66 | 3 | 5 | `backend/chat_parser.py:155 verify_private` |
| 35 | 30 | 118 | 3 | 3 | `actions/collect_history.py:87 execute` |
| 34 | 32 | 169 | 6 | 6 | `stores/history_repo.py:713 HistoryRepo.recover_media` |
| 34 | 27 | 73 | 6 | 0 | `services/undo_service.py:209 migrate_global_history` |
| 33 | 22 | 90 | 1 | 8 | `stores/history_repo.py:167 rename_if_same_conversation` |
| 31 | 29 | 92 | 3 | 3 | `actions/click_user.py:87 execute` |
| 31 | 26 | 37 | 3 | 0 | `services/run/coordinator.py:89 _execute_cycle` |
| 29 | 26 | 112 | 3 | 13 | `stores/history_repo.py:322 HistoryRepo.append` |
| 28 | 23 | 50 | 3 | 0 | `stores/label_store.py:252 _normalized` |
| 27 | 23 | 126 | 1 | 12 | `backend/visual_click.py:56 find_and_click` |
| 26 | 22 | 137 | 2 | 10 | `backend/media_handler.py:224 attach_image` |
| 25 | 20 | 23 | 3 | 0 | `services/history/export.py:56 migrate_install` |

### 1.2 Cognitive complexity (Sonar-style, own AST implementation)

median **1** · mean **3.0** · p90 **7** · max **93** · **28 functions (2.7 %) over 15**.
Top: `sync_conversation` 93, `Collector._tick` 61, `ScrollParser.collect` 39,
`HistoryRepo.recover_media` 32, `verify_private` 31, `CollectHistory.execute` 30.

### 1.3 Nesting depth

median 1 · **27 functions over 3 (2.6 %)** · **8 over 4** · max **8**
(`backend/config_manager.py:178 ConfigManager.set`, CC 17 in 31 LOC).
Runners-up: `bridge/collector_bridge.py:collector_command`, `undo_service.migrate_global_history`,
`history_repo.recover_media` (all 6).

### 1.4 Per-package complexity

| package | functions | CC > 10 | cog > 15 | LOC > 30 | nest > 4 | params > 4 | median CC |
|---|---|---|---|---|---|---|---|
| `core/` | 52 | 0 | 0 | 0 | 0 | 0 | 1.0 ✅ |
| `actions/` | 77 | 6 | 3 | 7 | 0 | 11 | 2.0 |
| `app/` | 19 | 0 | 0 | 0 | 0 | 1 | 2.0 |
| `bridge/` | 198 | 4 | 0 | 7 | 1 | 2 | 2.0 |
| `backend/` | 178 | 19 | 8 | 25 | 3 | 13 | 3.0 |
| `services/` | 239 | **26** | 7 | 20 | 2 | 9 | 3.0 |
| `stores/` | 267 | **20** | **10** | 24 | 2 | 11 | 3.0 |

---

## 2. 📏 Size & volume metrics

| Metric | Measured | Threshold | Verdict |
|---|---|---|---|
| Production Python | 108 files · 18,250 LOC · 13,852 SLOC · 957 comment lines | — | — |
| Function length | median **7** · mean 12.8 · p90 27 · max **295** | ≤ 20–30 | **164 > 20 (15.9 %)**, **83 > 30 (8.0 %)**, 30 > 50 |
| File length | median 66 · p90 373 · max **922** (`stores/history_repo.py`) | — | **20 files > 200 SLOC, 14 > 300** |
| Class length | 120 classes · median 44 · max **1,136** (`HistoryRepo`) | ≤ 200–300 | **16 > 200, 10 > 300** |
| Methods / class | median 4 · mean 7.2 · max **44** | ≤ 10–15 | **27 > 10, 15 > 15** |
| Parameters / function | median 1 · p90 3 · max **20** | ≤ 3–4 | **65 > 3, 47 > 4** |

Largest files: `stores/history_repo.py` 922 · `services/collector_service.py` 615 ·
`stores/media_store.py` 592 · `stores/history_db.py` 570 · `services/undo_service.py` 536 ·
`backend/chat_parser.py` 490 · `services/db_service.py` 471 · `bridge/history_bridge.py` 442.

Longest parameter lists (all `__init__`s / factories — introduce a config object):
`actions/scroll_parse.py:__init__` **20**, `backend/scroll_parser.py:__init__` **19**,
`chat_parser.sync_conversation` **14**, `actions/click_user.py:__init__` **13**,
`history_repo.append` **13**, `visual_click.find_and_click` **12**.

---

## 3. 🔗 Coupling & cohesion

### 3.1 Package coupling (internal imports only)

| package | Ce (depends on) | Ca (depended on) | **I = Ce/(Ca+Ce)** | depends on |
|---|---|---|---|---|
| `core` | 0 | 4 | **0.00 ✅** | — |
| `stores` | 2 | 4 | 0.33 | backend, core |
| `actions` | 1 | 2 | 0.33 | backend |
| `backend` | 4 | **6** | 0.40 | actions, bridge, services, stores |
| `services` | 4 | 3 | 0.57 | actions, backend, core, stores |
| `bridge` | 4 | 1 | **0.80** | backend, core, services, stores |
| `app` | 4 | 1 | **0.80** | backend, core, services, stores |
| `main` | 2 | 0 | 1.00 | app, backend |

⚠️ `backend` → `bridge` exists (`backend/bridge.py` re-exports `bridge.router`), i.e. an
**upward dependency that breaks the "arrows flow down only" rule** from
`docs/REFACTOR_2026-09-09_DESIGN.md` §2. `services/history` and `services/run` also import
`backend.*` instead of going through `stores/`.

### 3.2 File coupling — hot spots

| Most dependent (Ce) | Ce | Ca | I | | Most depended-upon (Ca) | Ca | Ce | I |
|---|---|---|---|---|---|---|---|---|
| `bridge/router.py` | **14** | 1 | 0.93 | | `backend/cdp_client.py` | **22** | 0 | **0.00** |
| `backend/config_manager.py` | 9 | 3 | 0.75 | | `actions/base_action.py` | 19 | 2 | 0.10 |
| `app/bootstrap.py` | 7 | 1 | 0.88 | | `core/events.py` | 18 | 0 | **0.00** |
| `bridge/context.py` | 6 | 2 | 0.75 | | `core/result.py` | 10 | 0 | **0.00** |
| `services/history/__init__.py` | 6 | 0 | 1.00 | | `backend/dom_probe.py` | 7 | 0 | 0.00 |
| `backend/scroll_parser.py` | 5 | 2 | 0.71 | | `stores/jsonio.py` | 7 | 0 | 0.00 |
| `services/run/coordinator.py` | 5 | 0 | 1.00 | | `stores/user_memory.py` | 6 | 0 | 0.00 |

`backend/cdp_client.py` (Ce 0, Ca 22) and `core/*` (Ce 0) are exactly the stable
abstractions you want. `bridge/router.py` at Ce 14 / I 0.93 is the single most
change-prone file in the repo and it is also the file with the highest churn.

### 3.3 Cohesion (LCOM)

| Metric | Value | Target |
|---|---|---|
| Classes with ≥ 2 methods | 82 | — |
| **LCOM4 = 1 (cohesive)** | **14 / 82 (17 %)** | → all |
| LCOM4 > 1 (split candidates) | **68** | → 0 |
| LCOM4 max | **10** | — |
| LCOM\* (Henderson–Sellers, 0 = perfect) | mean **0.77** · median 0.80 · 65/71 over 0.5 | → 0 |

God-class candidates (methods / LOC / LCOM4 / LCOM\*):

| Class | methods | LOC | fields | LCOM4 | LCOM* |
|---|---|---|---|---|---|
| `stores/history_repo.py:HistoryRepo` | **44** | **1,136** | 33 | 8 | 0.94 |
| `stores/label_store.py:LabelStore` | 38 | 463 | 19 | 8 | 0.93 |
| `services/collector_service.py:Collector` | 36 | 701 | 60 | 5 | 0.93 |
| `stores/media_store.py:MediaStore` | 33 | 642 | 30 | 5 | 0.94 |
| `bridge/history_bridge.py:HistoryBridge` | 31 | 490 | 18 | 4 | 0.88 |
| `bridge/stack_bridge.py:StackBridge` | 31 | 298 | 19 | 3 | 0.92 |
| `stores/history_db.py:HistoryDB` | 30 | 492 | 27 | 6 | 0.96 |
| `services/db_service.py:DbManager` | 27 | 502 | 22 | 4 | 0.91 |
| `services/undo_service.py:UndoService` | 26 | 544 | 33 | 5 | 0.92 |
| `stores/user_memory.py:UserMemory` | 21 | 228 | 5 | 3 | 0.78 |

---

## 4. 🧪 Test quality

| Metric | Target | Measured | Verdict |
|---|---|---|---|
| Line coverage | ≥ 80 % | **77.17 %** (8,249 / 10,380 stmts, 2,131 missed) | 🟡 |
| Branch coverage | ≥ 75 % | **68.85 %** (1,972 / 2,864 branches, 402 partial) | 🔴 |
| Mutation score | ≥ 70 % | **49.6 %** (120 / 242) | 🔴 |
| Test-to-code ratio | ~1:1 | **1.15 : 1** (25,708 test SLOC / 22,307 prod SLOC) | 🟢 |
| Suite green | 100 % | **1,323 pass / 314 fail** / 2 skipped / 1 xfail (19.2 % red) | 🔴 |

### 4.1 Coverage by package (line / branch)

| package | lines | branches | verdict |
|---|---|---|---|
| `core/` | **100.0 %** | 91.7 % | 🟢 |
| `stores/` | 89.3 % | 78.7 % | 🟢 |
| `backend/` | 82.8 % | 78.3 % | 🟡 |
| `actions/` | 83.6 % | 61.6 % | 🟡 |
| `services/` | 77.8 % | 67.1 % | 🟡 |
| `main.py` | 78.9 % | 50.0 % | 🟡 |
| `bridge/` | **60.9 %** | **41.2 %** | 🔴 |
| `app/` | **49.0 %** | **8.8 %** | 🔴 |

Worst-covered files: `backend/preset_store.py` 0 % · `app/lifecycle.py` 16.4 % ·
`actions/wait_page.py` 22.4 % · `services/undo_service.py` 27.7 % (443 stmts) ·
`bridge/undo_bridge.py` 32.0 % · `bridge/stack_bridge.py` 34.3 % ·
`bridge/label_bridge.py` 39.0 % · `app/window.py` 41.8 %.

### 4.2 Mutation score (own first-order AST mutator, 15 mutants × 17 modules)

| module | mutants | killed | score | tests used |
|---|---|---|---|---|
| `core/di.py` | 15 | 15 | **100 %** | unit/core |
| `core/result.py` | 15 | 14 | **93 %** | core contracts |
| `backend/criteria_engine.py` | 15 | 14 | **93 %** | criteria engine |
| `backend/person_filter.py` | 15 | 13 | **87 %** | person filter |
| `services/run/coordinator.py` | 15 | 12 | **80 %** | engine/action tests |
| `stores/history_models.py` | 15 | 10 | 67 % | history models |
| `backend/chat_parser.py` | 15 | 10 | 67 % | chat parser |
| `services/run/error_recovery.py` | 15 | 9 | 60 % | action engine |
| `services/run/hooks.py` | 15 | 7 | 47 % | action engine |
| `services/run/progress.py` | 15 | 5 | 33 % | action engine |
| `backend/scroll_parser.py` | 15 | 5 | 33 % | scroll pipeline |
| `core/events.py` | 15 | 3 | 20 % | events |
| `services/run/state_machine.py` | 15 | 2 | 13 % | action engine |
| `services/history/query.py` | 15 | 1 | **7 %** | only 2 test files touch it |
| `services/history/mutate.py` | 15 | 0 | **0 %** | only 2 test files touch it |
| `services/history/export.py` | 15 | 0 | **0 %** | only 2 test files touch it |
| `core/interfaces.py` | 2 | 0 | 0 % | protocols only |
| **TOTAL** | **242** | **120** | **49.6 %** | |

Read this as: **where tests exist and assert, they are strong (93–100 %)**; the score is
dragged down by the modules the refactor **orphaned** — `services/history/{query,mutate,export}`
are executed by only 2 test files each, and `services/run/*` lost its contract tests in the
merge (§7).

---

## 5. 🚨 Code smells

| Smell | Count | Worst cases |
|---|---|---|
| **Duplicated code** (clone detection, ≥ 6-line spans) | **Python 8.67 %** (1,387 / 16,005 SLOC, 79 groups) · **JS 9.59 %** (811 / 8,455 SLOC, 52 groups) | `backend/dom_highlight.py` 60-line clone ×2; `bridge/router.py` 11 lines ×3; 9-line block copied across 6 `actions/*` + `bridge/collector_bridge.py`; `ui/js/sash-grid.js` 101 dup lines, `presets-ui.js` 84, `labels.js` 83, `history-store.js` 82 |
| **Dead code** (vulture ≥ 60 % conf.) | **201 findings** — 134 unused methods, 28 classes, 11 vars, 10 properties, 9 attributes, 8 functions, 1 import · **7 at ≥ 90 %**, 5 at 100 % | 100 %: `backend/cdp_client.py:35` (exc_type, tb), `services/run/coordinator.py:53` (scroll_parser), `services/run/hooks.py:68/71/74` (coordinator) |
| **Long methods** (> 30 LOC) | **83** | `sync_conversation` 295, `Collector._tick` 212, `ScrollParser.collect` 192, `recover_media` 169 |
| **God classes** (> 15 methods) | **15** | `HistoryRepo` (44), `LabelStore` (38), `Collector` (36), `MediaStore` (33), `HistoryBridge` (31), `StackBridge` (31) |
| **Feature envy** (method touches another object more than itself) | **22 candidates** | `MessageRecord.from_dict` (14 foreign / 0 self), `HistoryRepo._ui_record` (13/3), `UserMemory.upsert_user` (11/5), `MarkMessaged.execute` (7/1), `ScrollParser._to_dict` (6/0) |
| **Dispensables** | 10 compat re-export shims + 1 bridge shim | `backend/{history_repo,media_store,preset_store,user_memory,history_db,history_models,history_service,db_manager,label_store,collector}.py` (3–7 code lines each, `# noqa: F401`), `backend/bridge.py` (12 lines) |
| **Long parameter lists** (> 4) | **47** | `scroll_parse.__init__` 20, `ScrollParser.__init__` 19 |

Note: ~28 of the vulture "unused class" hits are `actions/*` blocks registered through
`__init_subclass__` — false positives. Real dead code ≈ **180 findings**, of which the
5 × 100 %-confidence ones are safe immediate deletions.

---

## 6. 📉 Maintainability

### 6.1 Maintainability Index (radon, 0–100; A ≥ 20, B 10–19, C < 10)

mean **64.0** · median 62.3 · **A: 100 files · B: 6 · C: 2**

| file | MI | rank | SLOC |
|---|---|---|---|
| `stores/history_repo.py` | **0.0** | **C** | 922 |
| `backend/chat_parser.py` | **6.3** | **C** | 490 |
| `stores/media_store.py` | 9.4 | B | 592 |
| `services/undo_service.py` | 10.2 | B | 536 |
| `services/collector_service.py` | 12.0 | B | 615 |
| `stores/label_store.py` | 14.0 | B | 419 |
| `services/db_service.py` | 14.6 | B | 471 |
| `services/history/export.py` | 15.7 | B | 137 |

Per package (mean MI): `core` **87.0** ✅ · `actions` 78.2 · `backend` 73.2 · `app` 71.3 ·
`bridge` 54.5 · `stores` 53.4 · **`services` 42.0** 🔴.

### 6.2 Technical-debt ratio (Sonar-style estimate)

```
development cost  = 0.06 d × 18,250 LOC            = 1,095 dev-days
remediation       = 35 fn CC>15 × 1.5 h            =   53 h
                    83 long methods × 0.75 h       =   62 h
                    15 god classes × 6 h           =   90 h
                    314 red tests × 0.4 h          =  126 h
                    2,198 duplicated lines         =   60 h
                    dead code cleanup              =   25 h
                  --------------------------------------------
                                                   ≈  416 h ≈ 52 dev-days
TDR = 52 / 1,095 = 4.7 %
```
4.7 % is *acceptable* (Sonar's A-band is < 5 %), but it is dominated by the 314 failing
tests — fix those and the number drops below 3 %.

### 6.3 Code churn (202 commits, 2026-09-04 → 2026-09-09)

| file | commits | | file | commits |
|---|---|---|---|---|
| `backend/bridge.py` | **38** | | `backend/history_service.py` | 15 |
| `ui/js/stack-dnd.js` | **35** | | `backend/chat_agent_js.py` | 15 |
| `backend/action_engine.py` | 24 | | `backend/history_repo.py` | 14 |
| `ui/js/app.js` | 22 | | `backend/js/chat_agent.js` | 14 |
| `backend/collector.py` | 20 | | `backend/history_db.py` | 12 |
| `backend/config_manager.py` | 19 | | `actions/__init__.py` | 12 |
| `main.py` | 18 | | `backend/media_store.py` | 10 |
| `backend/chat_parser.py` | 17 | | `stores/user_memory.py` | 9 |

High churn + high coupling for `backend/bridge.py`, `backend/config_manager.py` and
`main.py` — exactly the three files involved in the P0 import breakage.

### 6.4 Bug density (proxy)

**63 of 202 commits (31 %) are fix / bug / revert / regress commits** over 18.25 KLOC
≈ **3.5 fix-commits per KLOC**. Not a steady-state defect rate (6-day window, heavy
refactor), but it says the refactor is being validated by trial and error rather than by
tests — consistent with the 19.2 % red suite.

---

## 7. 📈 Delta vs. the previous commit (`b33e312`, before your latest fixes)

Same command, same ignore set:

| | `b33e312` | HEAD (`392fdff` + `032ae5f`) | Δ |
|---|---|---|---|
| tests collected | 1,921 | 1,583 | **−338** |
| failing | **733** | **314** | **−419 (−57 %)** |
| failing share | 38.2 % | 19.8 % | −18.4 pp |
| Python test files | **120** | **95** | **−26 files / −382 tests** |

So: **real progress on correctness** (failures more than halved, and the split stores /
`bridge/` decomposition landed), **but the merge deleted 26 test files**:

`test_collect_history_contract` (42) · `test_scroll_parse_contract` (34) ·
`test_base_action_contract` (25) · `test_click_user_tab_verify` (24) ·
`test_type_message_block` (21) · `test_undo_bridge` (19) · `test_wait_page_block` (17) ·
`test_stack_bridge_contract` (17) · `test_custom_find_block` (17) ·
`test_click_tab_blocks` (15) · `test_search_users_contract` (14) ·
`test_attach_image_block_plumbing` (14) · `test_label_bridge` (13) ·
`test_bridge_router_rules` (12) · `test_pause_block` (11) · `test_people_bridge` (10) ·
`test_layout_bridge` (10) · `test_history_bridge_wire` (10) · `test_db_bridge` (9) ·
`test_core_result` (9) · `test_core_events` (9) · `test_cdp_bridge` (9) ·
`test_stores_migration` (7) · `test_core_di` (7) · `test_collector_bridge` (7) ·
`bridge_harness.py` (helper). **Only 1 test file was added** (`test_main_entry.py`).

That is the single biggest quality regression in this window: coverage went *down* not
because code got worse but because **382 tests were dropped** — which is also why
`services/*` and `bridge/*` show low coverage and 0–20 % mutation scores today.

---

## 8. 🗺️ Structured phases before the next refactor

| Phase | Goal | Work | Est. |
|---|---|---|---|
| **0 — Stabilise** | green suite, app boots | P0-3 `UndoStore` API, P0-4 `save()/flush()` on bookmark/undo/labels stores, P0-5 import `get_action_class` in `services/run/coordinator.py`, P0-6 move `main.py` entry tests to `app/`, P0-7 delete/fix the stale migration test | 0.5–1 d |
| **1 — Restore the safety net** | ≥ 1,900 tests | Re-add the 26 deleted test files against the *new* layout (`bridge/*`, `services/run`, `services/history`); add `app/` + `bridge/` coverage | 2–3 d |
| **2 — Break the bloaters** | CC ≤ 10 / LOC ≤ 30 | `sync_conversation` (130), `Collector._tick` (82), `ScrollParser.collect` (44), `recover_media`, `attach_image`, `find_and_click`; split the 5 worst god classes (`HistoryRepo` first — MI 0.0, LCOM4 8) | 3–5 d |
| **3 — Raise test strength** | branch ≥ 75 %, mutation ≥ 70 % | Branch tests for `bridge/*` (41 % branch) and `app/*` (9 %); assertion-level tests for `services/history/*` and `services/run/state_machine` | 2–3 d |
| **4 — De-duplicate & delete** | dup < 5 %, 0 dead code | Extract `dom_highlight` probe builders, the `actions/*` 9-line block, `bridge/router` repeated handlers; JS: `sash-grid`, `presets-ui`, `labels`; delete the 5 × 100 %-confidence dead symbols and retire the 10 `backend/*` shims | 2 d |
| **5 — Enforce** | keep the numbers | Add `radon cc -nc`, `lizard -Tcyclomatic_complexity=10`, `vulture --min-confidence 90`, `pytest --cov --cov-branch --cov-fail-under=80` to CI | 0.5 d |

---

## 9. 🔬 Method & reproduction

| Metric | Tool | Command / implementation |
|---|---|---|
| Cyclomatic CC, MI, raw LOC | radon 6.0.1 | `radon cc/mi/raw` via Python API |
| Cognitive complexity, nesting, params, LCOM4, LCOM\*, feature envy, coupling Ca/Ce/I | own AST analysers (`/tmp/metrics.py`, `/tmp/coupling.py`) | Sonar-style cognitive rules; LCOM4 = connected components over shared `self.*` fields; LCOM\* = Henderson–Sellers |
| JS size/complexity | lizard 1.24 | `lizard ui/js backend/js bridge -l javascript` → 852 funcs, 7,515 NLOC, avg CCN 3.6, 21 funcs CCN > 10 |
| Duplication | own token-window clone detector (`/tmp/dup2.py`) | 25-token windows, literal-aware keys, import/docstring boilerplate filtered, ≥ 6-line spans, non-overlapping |
| Coverage | coverage.py 7.16 + pytest-cov | `pytest tests --cov=core,actions,backend,bridge,services,stores,app,main --cov-branch` |
| Mutation score | own first-order AST mutator (`/tmp/mutate2.py`) | 8 operators (compare/arith/bool/aug swap, `not` drop, `True↔False`, int+1, `return → None`, negate `if`), 15 random mutants per module, tests chosen from a per-file coverage matrix |
| Dead code | vulture | `vulture <pkgs> --min-confidence 60/90/100` |
| Churn / bug-density | git | `git log --name-only`, `--grep=fix\|bug\|revert\|regress` |

**Environment:** Python 3.11.2, PySide6 6.11.2 (headless via `tools/build_stubs.py` +
`QT_QPA_PLATFORM=offscreen`), pytest 9.1.1, 1640 tests in ~175 s.

**Caveats (honest):**
1. Coverage/mutation/suite numbers are measured **after** the two hotfixes in `032ae5f`;
   at `392fdff` as committed, 24 test modules could not even be imported.
2. radon's raw lexer chokes on 3 test files with hostile escape sequences
   (`test_message_injector_text.py`, `test_dom_probe_contract.py`,
   `test_history_models.py`) — they parse fine with CPython; their SLOC is a rounding error.
3. Mutation score covers 17 modules / 15 mutants each — a sample, not the whole codebase;
   a project-wide run needs ~10 × the compute.
4. Duplication percentages come from token-level clone detection; different tools
   (CPD, jscpd) will report different absolute numbers — treat them as relative.
5. `test_sash_webengine.py` needs a real WebEngine surface; it is green here but slow, and
   1 module (`test_stores_migration_rollback.py`) is excluded as stale (P0-7).
6. Bug-density uses fix-commit counts, not a defect tracker.
