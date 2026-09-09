# Refactor Plan — 4 Independent Parallel Areas

**Date:** 2026-09-09 · **Branch base:** `arena/01a08819-chat-v-bot` (`622e248`)
**Status:** design / planning — no production code changed by this document
**Supersedes:** `docs/REFACTOR_2026-09-09_DESIGN.md` §8 (phase list) is kept; this doc
turns those phases into four mergeable branches.

---

## 0. TL;DR — what the measurements actually say

Everything below was **re-measured on this checkout**, not copied from the previous
report. The headline discovery is that the test suite has been reporting a
fiction: **two test modules replace `sys.modules["PySide6"]` globally and never
restore it**, so ~154 tests were failing (and 24 modules were un-importable) for
reasons that have nothing to do with the code under test.

| Run | failed | passed | collection errors |
|---|---|---|---|
| `pytest tests` (as checked out) | **377** | 983 | **14** |
| − poisoner #1 (`test_run_service_paths.py`) | **268** | 1 364 | 1 |
| − poisoner #2 (`test_main_entry.py`) too | **223** | 1 380 | 1 |

So the real defect backlog is **223 failing tests**, and **79 % of them (176) have one
of two root causes** — both in `stores/`. Add the 27 tests that only fail because of
two missing imports in `services/run/` and the four areas account for
**365 of the 377** failures; the remaining ~12 need product decisions, not refactors.

| root cause | tests | fix lands in | area |
|---|---|---|---|
| `'UndoStore' object has no attribute 'history'` / `'index'` | **86** | `stores/undo_store.py` | **B** |
| `'BookmarkStore' object has no attribute 'save'` | **74** | `stores/bookmark_store.py` | **B** |
| `NameError: name 'get_action_class' is not defined` | **25** | `services/run/coordinator.py:42` | **A** |
| `TypeError: stat: path should be … not AtomicJsonStore` | **16** | `stores/atomic.py` + small stores | **B** |
| `NameError: name 'UserRecord' is not defined` | 2 | `services/run/progress.py:150` | **A** |
| `ValueError: invalid transition: idle -> paused` | 1 | `services/run/state_machine.py` | C |
| `AttributeError: 'str' object has no attribute 'get'` | 3 | `backend/config_manager.py` | D |
| 17 one-off assertion failures (world switching, media dirs, `cleared` marker, `RepeatMarker` identity) | 17 | services / actions | C, D |
| **total** | **223** | | |

**Production import health: OK.** `import main` succeeds (headless, with the
gcc stub libs from `tools/build_stubs.py`); there is **no** import error in
production code. What *is* broken in production is that the run engine raises
`NameError` the moment you load a stack (§5, P0-1/P0-2) — the app boots and
then cannot run a single action.

Coverage (measured, poisoner #1 removed): **80.0 % line / 69.7 % branch**
(10 381 statements, 2 864 branches).

---

## 1. Method & reproduction

| Metric | Tool | Command |
|---|---|---|
| LOC / SLOC / coupling Ca-Ce / classes / methods | own AST pass | `tools/metrics/metrics.py` (§11) |
| Cyclomatic CC, cognitive, nesting, params | own AST pass | `tools/metrics/deep.py` |
| LCOM4 (connected components over `self.*`), LCOM\* (Henderson–Sellers) | own AST pass | `tools/metrics/deep.py` |
| Coverage | coverage.py 7.16 + pytest-cov | `coverage run --branch --source=core,actions,backend,bridge,services,stores,app,main -m pytest tests --ignore=tests/integration/services/test_run_service_paths.py` |
| Dead code | vulture 2.16 | `vulture core actions backend bridge services stores app main.py --min-confidence 60` |
| Duplication | own token-window clone detector (6-AST-node windows, ≥ 2 files) | §3.6 |
| Suite health | pytest 9.1.1 | `QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs python -m pytest tests -q` |

**Environment:** Python 3.11.2, PySide6 6.11.2 headless
(`python tools/build_stubs.py /home/user/.venv /tmp/stublibs`, then
`LD_LIBRARY_PATH=/tmp/stublibs QT_QPA_PLATFORM=offscreen`), 1 604 tests in ~210 s.

**Honest caveats**

1. `tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine`
   **aborts the interpreter** in this sandbox (QtWebEngine needs a real GL/display).
   It is deselected in every measurement below; it is *not* counted as a defect.
2. Duplication percentages come from a token-window clone detector; CPD/jscpd will
   report different absolute numbers — read them as relative.
3. Dead-code counts use vulture; ~28 of the "unused class" hits in `actions/*` are
   false positives (blocks register through `__init_subclass__`).
4. `stores/history_repo.py` etc. are counted with `ast`, so multi-line strings
   (JS injected into the page) inflate raw LOC vs. SLOC.

---

## 2. Volume, and the 21 files over 200 SLOC

108 production Python files · **18 251 LOC · 15 322 SLOC** · 119 classes ·
866 methods · 160 module-level functions.

| package | files | SLOC | classes | god classes (≥ 15 mth) | mean fn CC |
|---|---|---|---|---|---|
| `stores` | 17 | 3 974 | 7 | 4 | 3.0 |
| `services` | 17 | 3 119 | 12 | 4 | 3.0 |
| `backend` | 33 | 3 794 | 15 | 3 | 3.0 |
| `actions` | 23 | 1 551 | 21 | 0 | 2.0 |
| `bridge` | 10 | 2 050 | 9 | 4 | 2.0 |
| `core` | 5 | 312 | 12 | 0 | 1.0 |
| `app` + `main.py` | 4 | 205 | 2 | 0 | 2.0 |

**Files > 200 SLOC (21):**

| SLOC | file | area |
|---|---|---|
| 1 070 | `stores/history_repo.py` | B |
| 664 | `services/collector_service.py` | C |
| 664 | `stores/media_store.py` | B |
| 605 | `stores/history_db.py` | B |
| 590 | `services/undo_service.py` | C |
| 547 | `services/db_service.py` | C |
| 540 | `backend/chat_parser.py` | D |
| 472 | `stores/label_store.py` | B |
| 449 | `bridge/history_bridge.py` | — (excluded) |
| 428 | `backend/dom_highlight.py` | D |
| 411 | `backend/scroll_parser.py` | D |
| 384 | `backend/message_injector.py` | D |
| 371 | `backend/history_query.py` | D |
| 337 | `bridge/router.py` | — (excluded) |
| 298 | `backend/media_handler.py` | D |
| 270 | `bridge/stack_bridge.py` | — (excluded) |
| 263 | `backend/cdp_client.py` | D |
| 261 | `backend/config_manager.py` | D |
| 242 | `actions/scroll_parse.py` | D |
| 230 | `stores/user_memory.py` | B |
| 204 | `stores/preset_store.py` | B |

---

## 3. Hotspots

### 3.1 Worst functions (cyclomatic CC)

| CC | cog | LOC | nest | params | function | area |
|---|---|---|---|---|---|---|
| **130** | 277 | **295** | 46 | 14 | `backend/chat_parser.py:358 sync_conversation` | D |
| **82** | 106 | **212** | 24 | 1 | `services/collector_service.py:293 Collector._tick` | C |
| 43 | 97 | 192 | 28 | 5 | `backend/scroll_parser.py:298 ScrollParser.collect` | D |
| 43 | 53 | 66 | 10 | 5 | `backend/chat_parser.py:155 verify_private` | D |
| 35 | 49 | 118 | 20 | 4 | `actions/collect_history.py:87 execute` | D |
| 34 | 111 | 169 | 21 | 7 | `stores/history_repo.py:713 HistoryRepo.recover_media` | B |
| 34 | 98 | 73 | 20 | 1 | `services/undo_service.py:209 migrate_global_history` | C |
| 33 | 42 | 90 | 9 | 9 | `stores/history_repo.py:167 rename_if_same_conversation` | B |
| 32 | 64 | 88 | 8 | 2 | `stores/media_store.py:426 _fetch_via_network` | B |
| 31 | 41 | 92 | 15 | 4 | `actions/click_user.py:87 execute` | D |
| 31 | 33 | 37 | 10 | 1 | `services/run/coordinator.py:89 _execute_cycle` | **A** |
| 29 | 42 | 112 | 12 | 14 | `stores/history_repo.py:322 HistoryRepo.append` | B |
| 28 | 34 | 50 | 8 | 1 | `stores/label_store.py:252 _normalized` | B |
| 27 | 31 | 126 | 15 | 12 | `backend/visual_click.py:56 find_and_click` | D |
| 26 | 35 | 137 | 14 | 10 | `backend/media_handler.py:224 attach_image` | D |
| 25 | 30 | 23 | 13 | 1 | `services/history/export.py:56 migrate_install` | C |

Median CC **2**, mean **4.2**, p90 **9**, max **130**; **75 functions (7.3 %) over CC 10**.

### 3.2 God classes

| class | methods | LOC | `self.*` fields | LCOM4 | LCOM\* | area |
|---|---|---|---|---|---|---|
| `stores/history_repo.py:HistoryRepo` | **44** | 1 136 | 33 | 2 | 0.94 | B |
| `stores/label_store.py:LabelStore` | **38** | 463 | 19 | 7 | 0.93 | B |
| `services/collector_service.py:Collector` | **36** | 701 | 60 | 2 | 0.93 | C |
| `stores/media_store.py:MediaStore` | **33** | 642 | 30 | 3 | 0.94 | B |
| `bridge/history_bridge.py:HistoryBridge` | 31 | 490 | 18 | 1 | 0.88 | — |
| `bridge/stack_bridge.py:StackBridge` | 31 | 298 | 19 | 1 | 0.92 | — |
| `stores/history_db.py:HistoryDB` | **30** | 492 | 27 | 4 | **0.96** | B |
| `services/db_service.py:DbManager` | **27** | 502 | 22 | 2 | 0.91 | C |
| `services/undo_service.py:UndoService` | **26** | 544 | 33 | 1 | 0.92 | C |
| `stores/user_memory.py:UserMemory` | 21 | 228 | 5 | 2 | 0.78 | B |
| `backend/cdp_client.py:CDPClient` | 20 | 215 | 18 | 3 | 0.81 | D |
| `stores/preset_store.py:PresetStore` | 20 | 212 | 8 | 1 | 0.80 | B |
| `backend/config_manager.py:ConfigManager` | 17 | 227 | 18 | 3 | 0.81 | D |

LCOM\* ≥ 0.5 for **65 of 71** multi-method classes — i.e. almost every class is a
bag of methods that barely share state, which is exactly why they *can* be split
without breaking callers.

### 3.3 Long parameter lists (> 5)

`actions/scroll_parse.py:__init__` **20** · `backend/scroll_parser.py:__init__` **20** ·
`chat_parser.sync_conversation` **14** · `history_repo.append` **14** ·
`actions/click_user.py:__init__` **13** · `visual_click.find_and_click` **12** ·
`history_repo._prepend` **12** · `actions/custom_find.py:__init__` **11** ·
`bridge/context.py:__init__` **11** · `media_handler.attach_image` **10**.

### 3.4 Coupling — most depended-upon (Ca) / most dependent (Ce)

| Ca | file | | Ce | file |
|---|---|---|---|---|
| **22** | `backend/cdp_client.py` | | **15** | `bridge/router.py` |
| **19** | `actions/base_action.py` | | 9 | `backend/config_manager.py` |
| **18** | `core/events.py` | | 9 | `services/run/coordinator.py` |
| **10** | `core/result.py` | | 9 | `app/bootstrap.py` |
| 7 | `backend/dom_probe.py` | | 7 | `services/history/__init__.py` |
| 7 | `stores/jsonio.py` | | 6 | `bridge/context.py` |
| 7 | `services/run/__init__.py` | | 5 | `services/collector_service.py` |
| 6 | `stores/history_db.py`, `stores/user_memory.py` | | 5 | `services/undo_service.py`, `backend/scroll_parser.py` |

`backend/cdp_client.py` (Ca 22 / Ce 0) and `core/*` (Ce 0) are the stable
abstractions — exactly what you want. `bridge/router.py` (Ce 15) is the most
change-prone file; per the ground rules it stays out of all four areas.

### 3.5 Package instability `I = Ce / (Ca + Ce)`

| package | Ce | Ca | I | depends on |
|---|---|---|---|---|
| `core` | 0 | 4 | **0.00** ✅ | — |
| `stores` | 2 | 4 | 0.33 | backend, core |
| `actions` | 1 | 2 | 0.33 | backend |
| `backend` | 4 | 6 | 0.40 | actions, bridge, services, stores |
| `services` | 4 | 3 | 0.57 | actions, backend, core, stores |
| `bridge` | 4 | 1 | 0.80 | backend, core, services, stores |
| `app` | 4 | 1 | 0.80 | backend, core, services, stores |
| `main` | 2 | 0 | 1.00 | app, backend |

Two layering inversions to note (deferred, §9):
* `stores/media_store.py:30` → `from backend import chat_agent_js` (upward `stores → backend`).
* `services/history/*` and `services/collector_service.py` import `backend.*`
  (history_query, chat_parser) instead of reaching the DB through `stores/`.

### 3.6 Duplication

| package | SLOC | clone groups (≥ 2 files, 6-node window) | ~duplicated lines | % |
|---|---|---|---|---|
| `actions` | 1 551 | 71 | ~888 | **57 %** |
| `bridge` | 2 050 | 28 | ~294 | 14 % |
| `stores` | 3 974 | 29 | ~354 | 9 % |
| `services` | 3 397 | 14 | ~270 | 8 % |
| `backend` | 3 794 | 13 | ~228 | 6 % |
| `core` | 312 | 0 | 0 | ✅ |
| `app` | 205 | 0 | 0 | ✅ |

Qualitatively verified clones worth extracting:
* the **skeleton shared by `actions/{click_back, click_main_tab, click_send, pause,
  conditional_skip, wait_page, custom_find, mark_messaged}.py`** (same `__init__` →
  `execute` → `Result` shape);
* the four **`backend/dom_highlight.py` probe builders** (`build_find_probe` 85 LOC,
  `build_click_probe` 95, `build_highlight_probe` 70, `build_clear_probe`) that all
  concatenate `_base_out_js()` with the same tail;
* the 9-line `to_dict()`/registry block copied through 6 `actions/*`.

---

## 4. Test suite — measured state

### 4.1 The three runs (this is the most important table in the document)

| # | command | failed | passed | coll. errors |
|---|---|---|---|---|
| 1 | `pytest tests` | 377 | 983 | **14** |
| 2 | `… --ignore=tests/integration/services/test_run_service_paths.py` | 268 | 1 364 | 1 |
| 3 | `… --ignore=<#1> --ignore=tests/test_main_entry.py --deselect=…test_grid_in_real_webengine` | **223** | 1 380 | 1 |

Delta #1→#2: **+381 tests collected, −109 failures, −13 collection errors.**
Delta #2→#3: **−45 failures** (27 of them `test_main_entry`'s own stale
`main.*` assertions, **18 collateral** in unrelated files).

### 4.2 Root causes of the 223 real failures

| # | root cause | tests | where the fix belongs | area |
|---|---|---|---|---|
| 1 | `AttributeError: 'UndoStore' object has no attribute 'history'` (+ `'index'`) | 86 | `stores/undo_store.py` | B |
| 2 | `AttributeError: 'BookmarkStore' object has no attribute 'save'` (+ 11 assertions that unwrap it) | 74 | `stores/bookmark_store.py` | B |
| 3 | `NameError: name 'get_action_class' is not defined` | 25 | `services/run/coordinator.py:42` | A |
| 4 | `TypeError: stat: path should be string… not AtomicJsonStore` | 16 | `stores/{atomic,session_store,settings_store}.py` | B |
| 5 | `AttributeError: 'str' object has no attribute 'get'` | 3 | `backend/config_manager.py` | D |
| 6 | `ValueError: invalid transition: idle -> paused` | 1 | `services/run/state_machine.py` | C |
| 7 | `NameError: name 'UserRecord' is not defined` (surfaces as assertion failures) | 2 | `services/run/progress.py:150` | A |
| 8 | 16 one-off assertion failures (world switching, media dirs, `cleared` marker, `RepeatMarker` identity …) | 16 | services / actions | C, D |

### 4.3 Coverage

| package | stmts | covered | line % | branches | branch % |
|---|---|---|---|---|---|
| `core` | 221 | 221 | **100.0 %** | 12 | 91.7 % |
| `stores` | 2 556 | 2 337 | 91.4 % | 726 | 82.1 % |
| `actions` | 916 | 766 | 83.6 % | 224 | 61.6 % |
| `backend` | 2 146 | 1 777 | 82.8 % | 696 | 78.3 % |
| `services` | 2 681 | 2 087 | 77.8 % | 852 | 67.1 % |
| `main` | 38 | 30 | 78.9 % | 2 | 50.0 % |
| `bridge` | 1 631 | 993 | **60.9 %** | 318 | **41.2 %** |
| `app` | 192 | 94 | **49.0 %** | 34 | **8.8 %** |
| **TOTAL** | **10 381** | **8 305** | **80.0 %** | **2 864** | **69.7 %** |

Worst-covered files: `backend/preset_store.py` 0 % · `app/lifecycle.py` 18.9 % ·
`actions/wait_page.py` 28.3 % · `services/undo_service.py` **32.1 % (443 stmts)** ·
`bridge/undo_bridge.py` 37.2 % · `bridge/stack_bridge.py` 38.0 % ·
`actions/click_send.py` 40.5 % · `bridge/label_bridge.py` 43.1 % ·
`app/window.py` 49.1 % · `bridge/cdp_bridge.py` 51.4 %.

### 4.4 Dead code (vulture ≥ 60 %)

**201 findings**: 134 unused methods, 28 classes, 11 variables, 10 properties,
9 attributes, 8 functions, 1 import. 5 at 100 % confidence (safe immediate
deletion): `services/run/coordinator.py:53` (`scroll_parser`),
`services/run/hooks.py:68/71/74` (`coordinator` ×3),
`backend/cdp_client.py:35` (`exc_type`, `tb`).

---

## 5. Prioritised problem list

`P0` = merge-blocking; the number in brackets is how many tests it unblocks.

| # | Prio | Problem | Evidence | Fix | Area |
|---|---|---|---|---|---|
| P0-1 | 🔴 | **Run engine cannot load a stack.** `services/run/coordinator.py:42` calls `get_action_class()`; the name is never imported. `bridge/stack_bridge.py:87` calls `engine.load_stack(blocks)` → `NameError` on every stack save/load. | reproduced: `RunCoordinator(...).load_stack([...])` → `NameError` | add `from actions.base_action import BaseAction, get_action_class` | **A** |
| P0-2 | 🔴 | **Single-target run cycle crashes.** `services/run/progress.py:10` imports `UserRecord` **inside `if TYPE_CHECKING:`**, so it does not exist at runtime; `progress.py:150` raises `NameError`. | `services/run/progress.py:150` | move the import out of `TYPE_CHECKING` (reuse the try/except fallback already in `coordinator.py:12-19`) | **A** |
| P0-3 | 🔴 | **Test harness poisons `sys.modules`.** `tests/integration/services/test_run_service_paths.py:12-26` replaces `PySide6` + `PySide6.QtCore` with stubs at *import* time, unconditionally on collection order, never restored. | run 1 vs run 2 | delete the stub block; the file only needs `services.run_service` (pure logic) — run it in a subprocess or import it with a real PySide6 present | **A** |
| P0-4 | 🔴 | **Second poisoner.** `tests/test_main_entry.py:333` calls `_install_qt_stubs()` at module level → `sys.modules.update({"PySide6", "PySide6.QtCore", …8 modules})`, never undone. Every module imported afterwards gets a fake `QObject`. | run 2 vs run 3 (−45 failures, −18 collateral) | scope it: save/restore `sys.modules` in `setUp`/`tearDown` (or an `ExitStack` context manager) | **A** |
| P0-5 | 🔴 | **24 test modules un-importable.** Consequence of P0-3: `bridge/router.py` is imported while `PySide6.QtCore.QObject` is a stub `class _QObject: pass`, so `Router = _build_router_class()` raises `TypeError: object.__init__() takes exactly one argument`. | 14 collection errors, all with the identical traceback | same fix as P0-3; add a `tests/conftest.py` that asserts real PySide6 is importable | **A** |
| P0-6 | 🔴 | **Stale test.** `tests/test_stores_migration_rollback.py:24` imports `migrate, needs_migration` from `stores.migration`, which only defines `migrate_legacy_config` and `_store_files_present`. | 1 collection error | retarget to `migrate_legacy_config` / delete | **A** |
| P0-7 | 🔴 | **Stale `main.*` contract tests** (23 of the 27 `test_main_entry` failures): `main.MainWindow`, `main.build_container`, `main._queue_path` no longer exist — they moved to `app/`. | `AttributeError: module 'main' has no attribute 'MainWindow'` | move those tests to `tests/unit/app/` and import from `app.bootstrap` / `app.window` | **A** |
| P1-1 | 🟠 | `UndoStore` API gap **[86 tests]**: tests call `.history()` / `.index()`; the class only has `get()/set()/push()`. `backend/config_manager.py:273` already calls `self.undo.history()`. | see §4.2 | add `history()` / `index()` (read-only projections of `get()`) | **B** |
| P1-2 | 🟠 | `BookmarkStore` API gap **[74 tests]**: no `save()`. | §4.2 | add `save()` delegating to `self._atomic.save()` | **B** |
| P1-3 | 🟠 | Small-store constructor contract is split in two **[16 tests]**: `BookmarkStore/UndoStore/BlockStore` take `(atomic: AtomicJsonStore \| None, path: str)`; `SettingsStore/SessionStore/LabelsFileStore/PresetStore` take a bare `path`. Tests call `SessionStore(atomic)` → `TypeError`. | `stores/session_store.py:38` vs `stores/undo_store.py:15` | unify on `atomic \| path` (+ `save()` everywhere) | **B** |
| P2-1 | 🟡 | `HistoryRepo` god class: 44 methods / 1 136 LOC / LCOM\* 0.94; `recover_media` CC 34, `append` CC 29 w/ 14 params, `rename_if_same_conversation` CC 33. | §3.2 | split into `HistoryRepo` (facade, same public names) + internal collaborators | **B** |
| P2-2 | 🟡 | `LabelStore` 38 mth / LCOM4 7 · `MediaStore` 33 mth / LCOM\* 0.94 · `HistoryDB` 30 mth / LCOM\* 0.96 · `UserMemory` 21 mth · `PresetStore` 20 mth. | §3.2 | extract cohesive sub-objects behind the existing method names | **B** |
| P2-3 | 🟡 | `Collector._tick` CC 82 / 212 LOC; `Collector` 36 methods, 60 fields. | §3.1 | state-machine extraction | **C** |
| P2-4 | 🟡 | `UndoService.migrate_global_history` CC 34 in 73 LOC, nesting 6; `UndoService` 26 mth / LCOM\* 0.92 / **32 % covered (443 stmts)**. | §3.1, §4.3 | split + tests | **C** |
| P2-5 | 🟡 | `DbManager` 27 mth / 502 LOC; `services/db_service.py` 76 % covered. | §3.2 | split lifecycle vs. query | **C** |
| P2-6 | 🟡 | `services/history/{query,mutate,export}.py` are executed by only 2 test files each (mutation score 0–7 % in the previous run). | prior report §4.2 | add contract tests, then split | **C** |
| P2-7 | 🟡 | Alias packages `services/history_service/` (`from services.history import *`) and `services/run_service/` (re-export shim) duplicate the seams. | `services/history_service/__init__.py` | delete after moving their 2 importers | **C** |
| P2-8 | 🟡 | `RunStateMachine` rejects `idle -> paused` (1 test). | §4.2 | allow or reclassify the transition | **C** |
| P3-1 | 🟢 | `backend/chat_parser.py:358 sync_conversation` — CC **130**, 295 LOC, 14 params, nesting 46 (cognitive 277). The single worst function in the repo. | §3.1 | extract phases (seek → slice → align → merge → persist) | **D** |
| P3-2 | 🟢 | `backend/scroll_parser.py:298 collect` CC 43 / 192 LOC; `ScrollParser.__init__` takes **20** params. | §3.1, §3.3 | config object + phase extraction | **D** |
| P3-3 | 🟢 | `backend/dom_highlight.py` — 4 probe builders with a duplicated tail (§3.6); `interpret_find` CC 17. | §3.6 | builder extraction | **D** |
| P3-4 | 🟢 | `backend/config_manager.py` Ce 9 (imports 9 stores); `ConfigManager.set` nesting 8; 3 failures `'str' object has no attribute 'get'`. | §3.4 | split per-section managers | **D** |
| P3-5 | 🟢 | `visual_click.find_and_click` CC 27 / 12 params; `media_handler.attach_image` CC 26 / 10 params. | §3.1 | parameter objects | **D** |
| P3-6 | 🟢 | `actions/*` skeleton duplication ~57 %; `click_user.execute` CC 31, `collect_history.execute` CC 35. | §3.6 | shared base + per-block `execute` | **D** |
| P3-7 | 🟢 | 11 `backend/*.py` compat shims are **test-only** (0 production importers, 126 test references); `backend/bridge.py` is the only live one (`app/bootstrap.py:9`). | measured | retire — **deferred to the cleanup PR** (§9) | D→§9 |
| P3-8 | 🟢 | 5 × 100 %-confidence dead symbols. | §4.4 | delete | **D** |
| P4-1 | ⚪ | `bridge/*` — 60.9 % line / 41.2 % branch; `HistoryBridge` 31 mth, `StackBridge` 31 mth; `bridge/router.py` Ce 15. | §4.3 | **out of scope by rule** — deferred (§9) | — |
| P4-2 | ⚪ | `app/*` — 49.0 % line / **8.8 % branch**; `app/lifecycle.py` 18.9 %. | §4.3 | deferred | — |
| P4-3 | ⚪ | Layering inversions `stores → backend.chat_agent_js` and `services → backend.{history_query,chat_parser}`. | §3.5 | deferred | — |

---

## 6. The four areas

Ground rules applied (from the task):

* every production file belongs to **exactly one** area → zero textual merge conflicts;
* public function/class signatures across area boundaries **do not change** —
  every split is internal, callers are untouched;
* `bridge/*.py`, `core/*.py`, `app/*.py`, `main.py` are **not** in any area;
* each area also owns a disjoint set of test files (§6.5).

### 6.1 AREA A — `refactor/a-startup-and-harness`

> **Goal:** make `pytest tests` collect 100 % and make the run engine able to load
> a stack. **No production behaviour changes beyond two missing imports.**

| | |
|---|---|
| **Branch** | `refactor/a-startup-and-harness` (from `arena/01a08819-chat-v-bot`) |
| **Est.** | 0.5–1 day |
| **Unblocks** | everything — B/C/D cannot be validated until this lands |

**Production files (2, 278 SLOC)**

| file | change |
|---|---|
| `services/run/coordinator.py` | add `from actions.base_action import BaseAction, get_action_class` (P0-1) |
| `services/run/progress.py` | move `from stores.user_memory import UserRecord` out of `if TYPE_CHECKING:` (P0-2) |

**Test-infrastructure files**

| file | change |
|---|---|
| `tests/integration/services/test_run_service_paths.py` | delete the `sys.modules["PySide6"]` stub block (P0-3) |
| `tests/test_main_entry.py` | scope `_install_qt_stubs()` with `unittest.mock.patch.dict(sys.modules, …)` / `ExitStack` (P0-4); move the 23 stale `main.*` tests to `tests/unit/app/` (P0-7) |
| `tests/test_stores_migration_rollback.py` | retarget to `migrate_legacy_config` or delete (P0-6) |
| `tests/conftest.py` **(new)** | repo root on `sys.path`; assert real `PySide6.QtCore.QObject` is importable (fails fast if anything stubs Qt again); optional `QT_QPA_PLATFORM=offscreen` default |
| `tests/unit/app/` **(new dir)** | the relocated `main`-entry tests |
| `pytest.ini` **(new)** | `testpaths = tests`, `addopts = -p no:cacheprovider --strict-markers`, `filterwarnings` for the known asyncio warnings |

**Exit criteria**

1. `pytest tests -q` → **0 collection errors**.
2. `python -c "import main"` succeeds.
3. `RunCoordinator(cdp=None, memory=None, criteria=None).load_stack([{"block_id":"pause","id":"A"}])` returns without raising.
4. Failing count drops from **377 → ≤ 223** (no area-A test may regress).
5. `tests/test_main_entry.py` and `tests/integration/services/test_run_service_paths.py` are green **and** the suite run before/after them individually is unchanged (poison check).

**Risk:** near zero. 2 production lines; the rest is test-only.

---

### 6.2 AREA B — `refactor/b-stores`

> **Goal:** close the three small-store API gaps (176 tests) and then decompose the
> six `stores/` god classes. Largest test payoff of the four areas.

| | |
|---|---|
| **Branch** | `refactor/b-stores` |
| **Est.** | 1 day (B1 contract repair) + 3 days (B2 god-class splits) |
| **Files** | all 17 files in `stores/`, **3 974 SLOC** |

**B1 — contract repair (do this first, land it as its own commit)**

| file | change |
|---|---|
| `stores/undo_store.py` | add `history()` and `index()` (read-only projections of `get()`) — P1-1, 86 tests |
| `stores/bookmark_store.py` | add `save()` → `self._atomic.save()` — P1-2, 74 tests |
| `stores/atomic.py` | accept an `AtomicJsonStore` **or** a path (`_coerce_path`) — P1-3 |
| `stores/session_store.py`, `stores/settings_store.py`, `stores/labels_file_store.py`, `stores/preset_store.py` | unify the constructor on `(atomic \| path)`; expose `save()` — P1-3, 16 tests |
| `stores/block_store.py` | keep as-is (already conforms); add tests for the two unused methods (`save_custom_block`, `delete_custom_block`) or delete them |

**B2 — god-class decomposition (internal splits only)**

| file | change |
|---|---|
| `stores/history_repo.py` (1 070 SLOC, 44 mth) | extract `MediaRecovery`, `ConversationIdentity` (rename/merge), `AppendPlanner` behind the existing `HistoryRepo` method names |
| `stores/media_store.py` (664, 33 mth) | extract `MediaFetcher` (`_fetch_one` / `_fetch_via_network`) and `MediaCachePolicy` (limits) |
| `stores/history_db.py` (605, 30 mth) | extract `SchemaMigrator` (`_add_missing_columns`, `_rebuild_legacy_messages`) |
| `stores/label_store.py` (472, 38 mth, LCOM4 7) | extract `LabelDefinitions` vs `LabelAssignments` vs `LabelFilter` |
| `stores/user_memory.py` (230, 21 mth) | extract `UserQuery` |
| `stores/preset_store.py` (204, 20 mth) | extract `PresetMigration` |

**Untouched inside the package (stable, high Ca):** `stores/history_models.py`,
`stores/jsonio.py`, `stores/migration.py` — other areas depend on them.

**Exit criteria**

1. All 176 P1 failures green.
2. No file in `stores/` over 400 SLOC; `HistoryRepo` under 30 public methods.
3. `grep -rn "from stores" services backend actions bridge app | wc -l` unchanged
   (no import in any other area needs editing).
4. `stores` coverage stays ≥ 90 % line / ≥ 80 % branch.

---

### 6.3 AREA C — `refactor/c-services`

| | |
|---|---|
| **Branch** | `refactor/c-services` |
| **Est.** | 3–4 days |
| **Files** | `services/**` **except** `services/run/coordinator.py` and `services/run/progress.py` (owned by A) — 17 files, **3 119 SLOC** |

| file | change |
|---|---|
| `services/collector_service.py` (664, 36 mth) | decompose `Collector._tick` (CC 82 / 212 LOC) into a tick state machine; extract `CollectorProbe` and `CollectorArchive` |
| `services/undo_service.py` (590, 26 mth, **32 % covered**) | split `migrate_global_history` (CC 34, nesting 6); extract `UndoProjection` and `UndoWorldStore`; add the missing tests (this file is the biggest uncovered block in the repo) |
| `services/db_service.py` (547, 27 mth) | split `DbLifecycle` (create/delete/clean/restore) from `DbRegistry` (remember/list/switch) |
| `services/history/__init__.py` + `query.py` + `mutate.py` + `export.py` (533) | add the contract tests that are missing (2 test files today), then split `HistoryExportService` (16 mth / 36 fields → LCOM\* 0.94) |
| `services/run/{error_recovery,hooks,state_machine}.py` | fix `idle -> paused` (P2-8); add branch tests (mutation score 13–60 % today) |
| `services/{cdp_service,layout_service,people_service}.py` | extract the duplicated status-forwarding helpers (§3.6, 8-copy clone) |
| `services/history_service/__init__.py`, `services/run_service/__init__.py` | **delete** the alias packages after repointing their 2 importers (`backend/history_service.py`, `backend/action_engine.py`, `tests/integration/services/test_run_service_paths.py`) |

**Exit criteria**

1. `Collector._tick` CC ≤ 15 and ≤ 60 LOC; `migrate_global_history` CC ≤ 10.
2. `services` line coverage ≥ 85 %, `services/undo_service.py` ≥ 70 %.
3. `services/run/*` mutation score ≥ 60 %.
4. Zero new imports of `backend.*` from `services/` (the existing 8 stay).

---

### 6.4 AREA D — `refactor/d-backend-actions`

| | |
|---|---|
| **Branch** | `refactor/d-backend-actions` |
| **Est.** | 4–5 days |
| **Files** | all of `backend/**` + `actions/**` — 50 files, **5 345 SLOC** |

| file | change |
|---|---|
| `backend/chat_parser.py` (540) | **the headline job**: `sync_conversation` CC 130 / 295 LOC / 14 params / nesting 46 → extract `SyncPlanner`, `ChunkReader`, `DeltaAligner`, `SyncPersister`; introduce a `SyncOptions` dataclass for the 14 params. Also `verify_private` CC 43. |
| `backend/scroll_parser.py` (411) | `collect` CC 43 / 192 LOC → phase extraction; `ScrollParser.__init__` 20 params → `ScrollOptions` dataclass |
| `backend/dom_highlight.py` (428) | extract the shared probe tail (`_base_out_js` + return block) shared by all 4 builders; `interpret_find` CC 17 |
| `backend/config_manager.py` (261, Ce 9) | split per-section managers; fix the 3 `'str' object has no attribute 'get'` failures; `ConfigManager.set` nesting 8 → guard clauses |
| `backend/media_handler.py`, `backend/visual_click.py` | `attach_image` CC 26 / 10 params, `find_and_click` CC 27 / 12 params → parameter objects |
| `backend/history_query.py`, `backend/message_injector.py`, `backend/tab_matcher.py`, `backend/dom_probe.py`, `backend/criteria_engine.py`, `backend/person_filter.py`, `backend/cdp_client.py` | targeted CC/param reductions; keep `cdp_client` (Ca 22) signature-stable |
| `actions/*` (23 files, 1 551 SLOC, ~57 % cloned) | extract the shared block skeleton into `actions/base.py`; reduce `collect_history.execute` CC 35 and `click_user.execute` CC 31; `scroll_parse.__init__` 20 params → options object |
| 5 × 100 %-confidence dead symbols | delete (`backend/cdp_client.py:35`) |

**Not in this branch (deferred, §9):** the 11 `backend/*.py` compat shims. They are
test-only, so deleting them rewrites 126 test-file imports owned by B and C —
that would break file-disjointness. They are retired by codemod in the final
cleanup PR after all four areas merge.

**Exit criteria**

1. No function in `backend/` or `actions/` over CC 25; `sync_conversation` CC ≤ 15.
2. `actions` duplication < 25 % (from ~57 %).
3. `backend` coverage ≥ 85 % line / ≥ 78 % branch; `actions` branch ≥ 70 %.
4. `backend/cdp_client.py`, `actions/base_action.py` public APIs byte-identical
   (Ca 22 / Ca 19 — everything depends on them).

---

### 6.5 Test-file ownership (disjoint)

Rule: **a test file belongs to the area that owns the production code its fix
must land in.** "Owns" means *responsible for it being green*; other areas may
run it but may not edit it.

| area | test files | of which currently failing |
|---|---|---|
| **A** | 3 (+ `tests/conftest.py` new, `tests/unit/app/` new) | 27 (all stale/poisoned) |
| **B** | 24 | 58 |
| **C** | 34 | 76 |
| **D** | 24 | 0 |
| **— (bridge / app / core)** | 10 | 0 |

**AREA A (3 + 2 new)**
`tests/integration/services/test_run_service_paths.py` · `tests/test_main_entry.py` ·
`tests/test_stores_migration_rollback.py` · **new** `tests/conftest.py` ·
**new** `tests/unit/app/`

**AREA B (24)**
`tests/test_history_repo.py` · `test_history_repo_conflicts.py` ·
`test_history_repo_lifecycle.py` · `test_history_db_unit.py` ·
`test_history_db_integrity.py` · `test_history_models_edges.py` ·
`test_media_store.py` · `test_media_store_limits.py` · `test_media_store_paths.py` ·
`test_media_recovery.py` · `test_media_recovery_e2e.py` · `test_media_layout.py` ·
`test_label_store_orphans.py` · `test_person_labels.py` **(34 F)** ·
`test_preset_store_defaults.py` · `test_preset_store_unit.py` ·
`test_user_memory_links.py` · `test_user_memory_unit.py` ·
`test_stores_atomic_jsonio.py` · `test_stores_small_stores.py` **(16 F)** ·
`test_stores_split.py` **(8 F)** · `test_db_schema_migration.py` ·
`tests/unit/backend/test_history_models.py` ·
`tests/unit/backend/test_label_store_dbmode.py`

**AREA C (34)**
`tests/integration/services/test_services_{cdp,layout,people,run,undo,history,db_gaps,collector_gaps}.py` ·
`test_action_engine_sequence.py` · `test_engine_standalone_run.py` ·
`test_archive_delete_undo.py` **(8 F)** · `test_people_undo.py` ·
`test_collector_state.py` **(6 F)** · `test_private_gate.py` ·
`test_db_manager.py` **(13 F)** · `test_db_manager_corrupt.py` ·
`test_db_migration.py` **(3 F)** · `test_db_switch_e2e.py` **(2 F)** ·
`test_db_switch_restart.py` **(7 F)** · `test_db_unified_world.py` **(5 F)** ·
`test_filter_purge.py` **(7 F)** · `test_scroll_only_seek.py` **(7 F)** ·
`test_search_users.py` · `test_repeat_loop.py` · `test_click_user_memory.py` **(2 F)** ·
`test_click_user_order.py` · `test_take_person.py` · `test_mark_person_messaged.py` ·
`test_live_status_and_order.py` **(6 F)** · `test_merge_undo_enabled.py` ·
`test_grid_persistence.py` **(17 F)** · `test_grid_layout_v2_migration.py` **(7 F)** ·
`test_history_service_lifecycle.py` **(4 F)** · `test_history_bridge.py` **(6 F)** ·
`test_recollect_after_clear.py` **(1 F)**

**AREA D (24)**
`tests/test_chat_parser_concurrent.py` · `test_chat_parser_delta.py` ·
`test_scroll_parse_pipeline.py` · `test_action_registry.py` ·
`test_attach_image.py` · `test_cdp_events.py` ·
`test_collect_history_block.py` · `test_collect_visual_and_live_refresh.py` ·
`test_find_click_visual.py` · `test_media_handler_paths.py` ·
`test_message_block_composer.py` · `test_message_injector_text.py` ·
`test_nick_placeholder.py` · `test_tab_matcher.py` ·
`test_visual_click_contract.py` · `tests/unit/backend/test_config_manager.py` **(1 F)** ·
`tests/unit/backend/test_config_manager_contract.py` **(10 F)** ·
`tests/unit/backend/test_criteria_engine.py` ·
`tests/unit/backend/test_criteria_engine_contract.py` ·
`tests/unit/backend/test_dom_highlight_contract.py` ·
`tests/unit/backend/test_dom_probe_contract.py` ·
`tests/unit/backend/test_person_filter_contract.py`

**No area (10):** `tests/test_bridge_router.py` · `tests/test_sash_webengine.py` ·
`tests/repro_bug2.py` · `tests/test_core_contracts.py` ·
`tests/test_core_logic_coverage.py` · `tests/unit/core/test_{core_integration,di,events,interfaces_full}.py`

> **Note on the C-listed failures caused by B.** 76 of C's failures (and 10 in D's
> list) have their *fix* in `stores/` (UndoStore / BookmarkStore). B's change makes
> them green without editing those files, which is exactly why test ownership is
> assigned by fix-location: **B edits `stores/*`, C/D do not touch the test files.**
> If B's repair turns out to require a test edit, it goes in the cleanup PR (§9).

---

## 7. Dependency map — proof the areas are independent

### 7.1 Cross-area import matrix (production import statements)

| from ↓ / to → | A | B | C | D | neutral (`core`/`bridge`/`app`/`main`) |
|---|---|---|---|---|---|
| **A** (2 files) | 1 | **3** | **3** | **4** | 2 |
| **B** (`stores/`) | 0 | 14 | **0** | **1**† | 4 |
| **C** (`services/`) | 0 | **6** | 15 | **8** | 7 |
| **D** (`backend/`+`actions/`) | 0 | **21**‡ | **5**‡ | 68 | 2 |
| **neutral** | 0 | 3 | 15 | 6 | 39 |

† `stores/media_store.py:30 → backend.chat_agent_js` — the only `B → D` edge; it points
at a leaf module with Ce 0, so it cannot transmit a D change into B.
‡ 12 of D→B and 4 of D→C are the **compat shims** (`backend/history_db.py` →
`stores/history_db.py`, etc.), which are frozen in all four areas.

### 7.2 What that proves

| Property | Status |
|---|---|
| **Textual independence** — no file in two areas | ✅ by construction (§6.1–6.4 lists are a partition of the 86 files in `stores/ services/ backend/ actions/`) |
| **B is a near-leaf**: `B → C = 0`, `B → A = 0`, `B → D = 1` (leaf module) | ✅ **B can merge without waiting for C or D**, and C/D cannot break B |
| **A is a leaf of size 2**: A depends on B/C/D but nothing depends on A except `services/run/__init__.py` (Ca 7) and `backend/action_engine.py` | ✅ A's diff is 2 lines → cannot conflict with B/C/D even if they refactor around it |
| **C ↔ D is the only real cycle** (`services/history` ↔ `backend/history_query`, `services/collector_service` ↔ `backend/chat_parser`, `services/undo_service` ↔ `backend/config_manager`) | ⚠️ **Top risk** — see 7.3 |
| **`bridge/` is downstream of everything and in no area** | ✅ per the rule: bridges call services through `BridgeContext` / `core.interfaces` Protocols, so internal service splits cannot break them — *provided the Protocol method names do not change* |
| **`core/` is Ce 0 / stable** | ✅ no area touches it |

### 7.3 The one risk, and the contract that neutralises it

C and D both refactor modules on the `services ↔ backend` cycle. Because the
**files** are disjoint, git will merge cleanly — but the **semantics** could
drift. The contract, enforced by the integration gate (§8.3):

1. **No area renames, moves, or changes the signature of any symbol that another
   area imports.** Every split is internal; the old public name stays and
   delegates. (Extracting `Foo._helper` into `FooHelper` is fine; renaming
   `Foo.bar` is not.)
2. Frozen for the duration — **nobody** may edit them:
   `core/*`, `bridge/*`, `app/*`, `main.py`, `stores/history_models.py`,
   `stores/jsonio.py`, `stores/migration.py`, `backend/cdp_client.py`,
   `actions/base_action.py`, and all 12 `backend/*.py` compat shims.
3. If an area genuinely needs a frozen file, it does **not** edit it: it raises a
   cross-area request and the change lands in the cleanup PR (§9).
4. `bridge/*` never changes ⇒ the JS wire API (`ui/js/**`) never changes ⇒ no
   front-end risk in any of the four areas.

---

## 8. Merge plan

### 8.1 Order

```
arena/01a08819-chat-v-bot
        │
        ├── refactor/a-startup-and-harness      ← merge FIRST (0.5–1 d)
        │        │                                unblocks measurement for B/C/D
        │        └─── main
        ├── refactor/b-stores        ─┐
        ├── refactor/c-services      ─┼─ merge in ANY order (independent, §7.2)
        └── refactor/d-backend-actions┘
                 │
                 └── cleanup/shim-retirement + bridge + app  ← FINAL (§9)
```

**1. A first.** B/C/D are developed against `arena/…` and rebased onto `main`
after A lands. A touches 2 production files that C is explicitly forbidden to
touch (`services/run/{coordinator,progress}.py`), so A→C rebases are clean.

**2. B, C, D in any order.** Recommended order if you want the fastest green:
**B** (176 tests) → **C** (5) → **D** (0), because B's repair also flips a large
number of C-owned test files to green.

**3. After each merge:** rebase the remaining branches, run the full suite,
compare the failure count against the table below.

### 8.2 Expected failure count after each merge

| after | change | expected failures |
|---|---|---|
| baseline (as checked out, 1 634 collected, **14 collection errors**) | — | **377** |
| **A** | −154 (harness de-poisoning) −27 (the two missing imports) | **≈ 196** (0 collection errors) |
| **A + B** | −176 (`UndoStore` 86, `BookmarkStore` 74, small-store contract 16) | **≈ 20** |
| **A + B + C** | −5 (`idle -> paused` 4, `cleared` marker 1) | **≈ 15** |
| **A + B + C + D** | −3 (`'str' object has no attribute 'get'`) | **≈ 12** |
| **+ cleanup PR** | −12 (remainder) | **0** |

The residual ~12 are the one-off assertions in §4.2 row 8; several need a *product*
decision rather than a refactor — e.g. `saved_media/history` vs `saved_media/work`,
`my_nick` not seeded into a freshly created world, `RepeatMarker` class identity.

### 8.3 Integration-test checklist (run after **every** merge)

**Gate 0 — collection** (blocks everything)
```bash
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  python -m pytest tests -q --co -p no:cacheprovider
# PASS = 0 errors. The 14 "object.__init__() takes exactly one argument"
#        errors are the canary for re-introduced sys.modules poisoning.
```

**Gate 1 — no Qt stubbing leaked into the process**
```bash
python - <<'EOF'
import sys; sys.path.insert(0, ".")
import importlib
for m in ["tests.test_main_entry",
          "tests.integration.services.test_run_service_paths"]:
    importlib.import_module(m)
from PySide6.QtCore import QObject
assert QObject.__init__.__objclass__.__module__.startswith("PySide6"), \
    "a test module stubbed PySide6 globally"
print("gate 1 OK")
EOF
```

**Gate 2 — the two P0 runtime bugs**
```bash
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from services.run import RunCoordinator
rc = RunCoordinator(cdp=None, memory=None, criteria=None)
rc.load_stack([{"block_id": "pause", "id": "A"}])   # P0-1
assert rc.get_stack(), "stack did not load"
from services.run.progress import UserRecord          # P0-2 must be importable
print("gate 2 OK")
EOF
```

**Gate 3 — app boots**
```bash
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs python -c \
  "import sys; sys.path.insert(0,'.'); import main; print('gate 3 OK')"
```

**Gate 4 — full suite, non-regression**
```bash
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  python -m pytest tests -q -p no:cacheprovider -rf \
  --deselect "tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine"
# PASS = failures <= the §8.2 row for this merge, and no test that was green
#        before this merge is now red.
```

**Gate 5 — cross-area contract (frozen files untouched)**
```bash
git diff --name-only main...HEAD | grep -E \
  '^(core|bridge|app)/|^main\.py$|^stores/(history_models|jsonio|migration)\.py$' \
  && echo "VIOLATION" || echo "gate 5 OK"
```
and, per area branch, that it touched **only** its own files:
```bash
git diff --name-only arena/01a08819-chat-v-bot...HEAD   # must be a subset of §6.x
```

**Gate 6 — public API parity** (run once, before A, then after the last merge)
```bash
python - > /tmp/api_before.txt <<'EOF'
import importlib, inspect, pkgutil, sys, json
sys.path.insert(0, ".")
sigs = {}
for pkg in ["core","actions","backend","bridge","services","stores","app","main"]:
    for m in pkgutil.walk_packages([pkg], pkg + "."):
        try: mod = importlib.import_module(m.name)
        except Exception: continue
        for name, obj in vars(mod).items():
            if name.startswith("_"): continue
            if inspect.isfunction(obj) or inspect.isclass(obj):
                try: sigs[f"{m.name}.{name}"] = str(inspect.signature(obj))
                except (TypeError, ValueError): pass
print(json.dumps(sigs, indent=1, sort_keys=True))
EOF
# after: regenerate and diff — only NEW symbols are allowed, no changes, no removals
```
(The one exception to "no removals" is the cleanup PR, which is allowed to delete
the 12 shims and the 5 dead symbols.)

**Gate 7 — metrics gate**
```bash
radon cc -nc core actions backend bridge services stores app main     # no fn > CC 25
vulture core actions backend bridge services stores app main.py --min-confidence 90   # 0 findings
coverage run --branch --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q --deselect "…test_grid_in_real_webengine"
coverage report --fail-under=80
```

### 8.4 Conflict-resolution protocol

| situation | rule |
|---|---|
| Two areas want the same file | impossible by construction — the file goes to exactly one area (§6.x). The other area uses the old API. |
| An area needs a change in a **frozen** file | do not edit it; open a cross-area request, land it in the cleanup PR |
| An area needs a change in a **non-frozen** file owned by another area | do not edit it; the owning area exposes what's needed, or the change waits for the cleanup PR |
| A test file owned by X is red because of Y's production code | Y fixes the production code; X owns the test and verifies. If the test itself must change, X does it **after** Y merges. |
| Rebase conflict | only `tests/conftest.py` (A) and `services/run/__init__.py` (C) are plausible hot spots; resolve in favour of A for conftest, and re-verify `services/run/__init__.py` exports (Ca 7) with Gate 2. |

---

## 9. Deferred — the final cleanup PR

Branch `cleanup/post-merge`, opened **after** A+B+C+D are on `main`.

| item | why deferred | size |
|---|---|---|
| **Retire the 11 test-only `backend/*.py` shims** (`history_repo`, `media_store`, `preset_store`, `user_memory`, `history_db`, `history_models`, `history_service`, `db_manager`, `label_store`, `collector`, `action_engine`) — 0 production importers, 126 test references | touching them rewrites test files owned by B and C, which would break file-disjointness | mechanical codemod: `from backend.X import Y` → `from stores.X import Y` / `from services.X import Y`, then delete |
| **`bridge/*`** — 60.9 % line / 41.2 % branch, `HistoryBridge` 31 mth, `StackBridge` 31 mth, `router.py` Ce 15 | excluded by the task's ground rule | 2 050 SLOC |
| **`app/*`** — 49.0 % line / **8.8 % branch**, `lifecycle.py` 18.9 %, `window.py` 49.1 % | excluded (`main.py`/`app/` are the entry points, not the refactor target) | 205 SLOC |
| **Layering inversions** — `stores/media_store.py → backend.chat_agent_js`; `services/history/* → backend.{history_query,chat_parser}` | each spans two areas | 4 import lines |
| **Re-add the 26 test files deleted in the previous merge** (per the prior report §7) | needs the new layout to be settled first | 382 tests |
| **JS duplication** — `ui/js/sash-grid.js` (101 dup lines), `presets-ui.js` (84), `labels.js` (83), `history-store.js` (82) | out of scope for the Python areas | ~350 lines |
| **CI gates** — `radon cc -nc`, `lizard -Tcyclomatic_complexity=10`, `vulture --min-confidence 90`, `pytest --cov --cov-branch --cov-fail-under=80` in CI | needs the numbers to be stable first | 0.5 d |

---

## 10. Summary table — the four areas at a glance

| | **A** startup & harness | **B** stores | **C** services | **D** backend & actions |
|---|---|---|---|---|
| branch | `refactor/a-startup-and-harness` | `refactor/b-stores` | `refactor/c-services` | `refactor/d-backend-actions` |
| production files | 2 | 17 | 17 | 50 |
| SLOC | 278 | 3 974 | 3 119 | 5 345 |
| test files owned | 3 + 2 new | 24 | 34 | 24 |
| tests unblocked | **181** (154 harness + 27 engine) | **176** | **5** | **3** |
| god classes | — | 4 | 4 | 2 |
| worst function | `_execute_cycle` CC 31 | `recover_media` CC 34 | `_tick` CC **82** | `sync_conversation` CC **130** |
| est. | 0.5–1 d | 1 d + 3 d | 3–4 d | 4–5 d |
| merge order | **1st** | any (recommended 2nd) | any | any |
| depends on | — | A (for measurement) | A | A |
| depended on by | all | C, D | D | C |
| cross-area risk | none | very low (leaf) | medium (cycle w/ D) | medium (cycle w/ C) |

---

## 11. Reproduction

The analysis scripts used for this document are committed under `tools/metrics/`
so every number here can be regenerated:

| script | produces |
|---|---|
| `tools/metrics/metrics.py` | per-module LOC / SLOC / Ca / Ce / classes / methods / worst CC → `file_stats.json`, `coupling.json` |
| `tools/metrics/deep.py` | cyclomatic CC, cognitive complexity, nesting depth, parameter counts, LCOM4, LCOM\* → `deep.json` |
| `tools/metrics/bisect_import.py` | the import-order bisect that identified `tests/test_main_entry.py` as the second `sys.modules` poisoner (imports test modules one at a time, then probes `Bridge.__new__` + `QObject.__init__`) |

```bash
.venv/bin/python tools/metrics/metrics.py     # writes file_stats.json, coupling.json
.venv/bin/python tools/metrics/deep.py        # prints the CC / god-class / LCOM tables
.venv/bin/python tools/metrics/bisect_import.py
```

```bash
# environment
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest pytest-cov radon vulture
python tools/build_stubs.py .venv /tmp/stublibs          # headless Qt shims
export LD_LIBRARY_PATH=/tmp/stublibs QT_QPA_PLATFORM=offscreen

# baseline
python -m pytest tests -q --co -p no:cacheprovider        # → 14 collection errors
python -m pytest tests -q -p no:cacheprovider -rf         # → 377 failed / 983 passed

# with the poisoners removed
python -m pytest tests -q -p no:cacheprovider -rf \
  --ignore=tests/integration/services/test_run_service_paths.py \
  --ignore=tests/test_main_entry.py \
  --deselect "tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine"
  # → 223 failed / 1380 passed
```


---

## 12. Full module inventory

Every production module: **LOC** (raw), **SLOC** (non-blank, non-comment),
**Ca** (modules that import it), **Ce** (modules it imports), classes / methods,
worst cyclomatic complexity, the area that owns it, and the issues it carries.

Legend — `CC n` = worst function's cyclomatic complexity · `god class` = ≥ 15
methods · `compat shim` = re-export-only `backend/*.py` · `Ca 0` = nothing imports it.

| # | File | LOC | SLOC | Ca | Ce | cls | mth | maxCC | Area | Issues |
|---|------|-----|------|----|----|-----|-----|-------|------|--------|
| 1 | `stores/history_repo.py` | 1230 | 1070 | 4 | 2 | 1 | 44 | 34 | B | >200 SLOC; CC 34 `recover_media`; 7 fn CC>10; 9 fn >30 LOC; god class HistoryRepo (44 mth, LCOM* 0.94) |
| 2 | `services/collector_service.py` | 776 | 664 | 2 | 5 | 2 | 36 | 82 | C | >200 SLOC; CC 82 `_tick`; 2 fn CC>10; 4 fn >30 LOC; god class Collector (36 mth, LCOM* 0.93) |
| 3 | `stores/media_store.py` | 750 | 664 | 2 | 2 | 1 | 33 | 32 | B | >200 SLOC; CC 32 `_fetch_via_network`; 5 fn CC>10; 4 fn >30 LOC; god class MediaStore (33 mth, LCOM* 0.94) |
| 4 | `stores/history_db.py` | 757 | 605 | 6 | 1 | 1 | 30 | 23 | B | >200 SLOC; CC 23 `_rebuild_legacy_messages`; 2 fn CC>10; 5 fn >30 LOC; god class HistoryDB (30 mth, LCOM* 0.96) |
| 5 | `services/undo_service.py` | 661 | 590 | 3 | 5 | 1 | 26 | 34 | C | >200 SLOC; CC 34 `migrate_global_history`; 6 fn CC>10; 5 fn >30 LOC; god class UndoService (26 mth, LCOM* 0.92) |
| 6 | `services/db_service.py` | 612 | 547 | 2 | 0 | 1 | 27 | 21 | C | >200 SLOC; CC 21 `delete`; 4 fn CC>10; 4 fn >30 LOC; god class DbManager (27 mth, LCOM* 0.91) |
| 7 | `backend/chat_parser.py` | 652 | 540 | 3 | 3 | 2 | 12 | 130 | D | >200 SLOC; CC 130 `sync_conversation`; 3 fn CC>10; 3 fn >30 LOC |
| 8 | `stores/label_store.py` | 555 | 472 | 2 | 0 | 1 | 38 | 28 | B | >200 SLOC; CC 28 `_normalized`; 3 fn CC>10; 3 fn >30 LOC; god class LabelStore (38 mth, LCOM* 0.93) |
| 9 | `bridge/history_bridge.py` | 511 | 449 | 1 | 1 | 1 | 31 | 12 | — | >200 SLOC; CC 12 `history_delete_person`; 2 fn CC>10; 4 fn >30 LOC; god class HistoryBridge (31 mth, LCOM* 0.88) |
| 10 | `backend/dom_highlight.py` | 465 | 428 | 2 | 1 | 0 | 0 | 17 | D | >200 SLOC; CC 17 `interpret_find`; 4 fn >30 LOC |
| 11 | `backend/scroll_parser.py` | 495 | 411 | 2 | 5 | 2 | 15 | 43 | D | >200 SLOC; CC 43 `collect`; 2 fn CC>10; 3 fn >30 LOC |
| 12 | `backend/message_injector.py` | 454 | 384 | 3 | 2 | 0 | 0 | 14 | D | >200 SLOC; CC 14 `click_send`; 4 fn >30 LOC |
| 13 | `backend/history_query.py` | 420 | 371 | 2 | 1 | 1 | 14 | 22 | D | >200 SLOC; CC 22 `_item`; 3 fn CC>10; 5 fn >30 LOC |
| 14 | `bridge/router.py` | 455 | 337 | 1 | 15 | 0 | 0 | 10 | — | >200 SLOC; 1 fn >30 LOC; Ce 15 |
| 15 | `backend/media_handler.py` | 360 | 298 | 1 | 3 | 1 | 1 | 26 | D | >200 SLOC; CC 26 `attach_image`; 2 fn CC>10; 1 fn >30 LOC |
| 16 | `bridge/stack_bridge.py` | 320 | 270 | 1 | 2 | 1 | 31 | 7 | — | >200 SLOC; god class StackBridge (31 mth, LCOM* 0.92) |
| 17 | `backend/cdp_client.py` | 311 | 263 | 22 | 0 | 4 | 31 | 13 | D | >200 SLOC; CC 13 `get_cookies`; god class CDPClient (20 mth, LCOM* 0.92) |
| 18 | `backend/config_manager.py` | 313 | 261 | 3 | 9 | 1 | 17 | 17 | D | >200 SLOC; CC 17 `set`; 2 fn CC>10; 1 fn >30 LOC; god class ConfigManager (17 mth, LCOM* 0.81); Ce 9 |
| 19 | `actions/scroll_parse.py` | 283 | 242 | 0 | 4 | 1 | 7 | 18 | D | >200 SLOC; CC 18 `run_pipeline`; 3 fn >30 LOC; Ca 0 |
| 20 | `stores/user_memory.py` | 266 | 230 | 6 | 0 | 2 | 21 | 14 | B | >200 SLOC; CC 14 `replace_all`; 1 fn >30 LOC; god class UserMemory (21 mth, LCOM* 0.78) |
| 21 | `stores/preset_store.py` | 244 | 204 | 3 | 1 | 1 | 20 | 11 | B | >200 SLOC; CC 11 `import_legacy`; 1 fn >30 LOC; god class PresetStore (20 mth, LCOM* 0.8) |
| 22 | `backend/dom_probe.py` | 217 | 199 | 7 | 0 | 0 | 0 | 14 | D | CC 14 `interpret`; 2 fn >30 LOC |
| 23 | `services/people_service.py` | 219 | 187 | 2 | 2 | 1 | 14 | 8 | C | — |
| 24 | `actions/collect_history.py` | 204 | 176 | 0 | 3 | 1 | 4 | 35 | D | CC 35 `execute`; 1 fn >30 LOC; Ca 0 |
| 25 | `services/layout_service.py` | 203 | 175 | 3 | 0 | 1 | 10 | 19 | C | CC 19 `normalize_grid_tree`; 2 fn CC>10; 1 fn >30 LOC |
| 26 | `actions/click_user.py` | 209 | 170 | 0 | 3 | 1 | 4 | 31 | D | CC 31 `execute`; 1 fn >30 LOC; Ca 0 |
| 27 | `services/history/mutate.py` | 177 | 162 | 0 | 1 | 1 | 11 | 19 | C | CC 19 `_merge_legacy_queue`; 4 fn CC>10; Ca 0 |
| 28 | `services/run/error_recovery.py` | 179 | 162 | 1 | 1 | 2 | 11 | 15 | C | CC 15 `_run_collect_phase`; 2 fn CC>10; 2 fn >30 LOC |
| 29 | `bridge/layout_bridge.py` | 187 | 160 | 1 | 3 | 1 | 8 | 13 | — | CC 13 `save_window_states`; 1 fn >30 LOC |
| 30 | `services/run/progress.py` | 181 | 158 | 1 | 3 | 3 | 15 | 14 | A | CC 14 `filter_by_labels`; 2 fn CC>10 |
| 31 | `backend/visual_click.py` | 187 | 151 | 4 | 4 | 0 | 0 | 27 | D | CC 27 `find_and_click`; 1 fn >30 LOC |
| 32 | `stores/history_models.py` | 196 | 149 | 4 | 0 | 4 | 8 | 15 | B | CC 15 `from_dict` |
| 33 | `bridge/undo_bridge.py` | 173 | 146 | 1 | 4 | 1 | 13 | 11 | — | CC 11 `push_global_history` |
| 34 | `stores/settings_store.py` | 168 | 141 | 1 | 1 | 1 | 11 | 7 | B | — |
| 35 | `services/history/export.py` | 153 | 137 | 0 | 1 | 1 | 16 | 25 | C | CC 25 `migrate_install`; 3 fn CC>10; 1 fn >30 LOC; god class HistoryExportService (16 mth, LCOM* 0.94); Ca 0 |
| 36 | `services/history/query.py` | 155 | 133 | 1 | 0 | 1 | 15 | 11 | C | CC 11 `load_app_settings`; god class HistoryQueryService (15 mth, LCOM* 0.89) |
| 37 | `bridge/label_bridge.py` | 156 | 128 | 1 | 1 | 1 | 15 | 6 | — | god class LabelBridge (15 mth, LCOM* 0.81) |
| 38 | `bridge/collector_bridge.py` | 147 | 127 | 1 | 1 | 1 | 9 | 11 | — | CC 11 `set_my_nick` |
| 39 | `services/run/hooks.py` | 151 | 125 | 1 | 0 | 3 | 14 | 8 | C | — |
| 40 | `services/run/coordinator.py` | 127 | 120 | 0 | 9 | 1 | 9 | 31 | A | CC 31 `_execute_cycle`; 2 fn CC>10; 2 fn >30 LOC; Ce 9; Ca 0 |
| 41 | `core/events.py` | 185 | 115 | 18 | 0 | 20 | 5 | 3 | — | — |
| 42 | `bridge/people_bridge.py` | 149 | 115 | 1 | 2 | 1 | 20 | 5 | — | god class PeopleBridge (20 mth, LCOM* 0.93) |
| 43 | `bridge/db_bridge.py` | 135 | 113 | 1 | 2 | 1 | 10 | 8 | — | 1 fn >30 LOC |
| 44 | `app/window.py` | 128 | 110 | 1 | 0 | 1 | 11 | 6 | — | — |
| 45 | `backend/person_filter.py` | 132 | 104 | 3 | 0 | 2 | 7 | 10 | D | — |
| 46 | `bridge/context.py` | 126 | 104 | 2 | 6 | 1 | 11 | 4 | — | — |
| 47 | `services/cdp_service.py` | 120 | 103 | 1 | 3 | 1 | 7 | 10 | C | 1 fn >30 LOC |
| 48 | `backend/tab_matcher.py` | 130 | 102 | 1 | 0 | 0 | 0 | 20 | D | CC 20 `score_tab`; 2 fn CC>10; 1 fn >30 LOC |
| 49 | `actions/custom_find.py` | 109 | 97 | 0 | 4 | 1 | 4 | 8 | D | Ca 0 |
| 50 | `bridge/cdp_bridge.py` | 118 | 94 | 1 | 1 | 1 | 12 | 4 | — | — |
| 51 | `backend/criteria_engine.py` | 102 | 87 | 2 | 0 | 2 | 8 | 7 | D | — |
| 52 | `stores/migration.py` | 117 | 86 | 1 | 1 | 0 | 0 | 20 | B | CC 20 `migrate_legacy_config`; 1 fn >30 LOC |
| 53 | `backend/chat_agent_js.py` | 118 | 84 | 0 | 0 | 0 | 0 | 3 | D | Ca 0 |
| 54 | `actions/registry.py` | 109 | 80 | 3 | 1 | 1 | 7 | 7 | D | — |
| 55 | `actions/mark_messaged.py` | 86 | 75 | 0 | 2 | 1 | 1 | 16 | D | CC 16 `execute`; 1 fn >30 LOC; Ca 0 |
| 56 | `actions/attach_image.py` | 82 | 73 | 0 | 3 | 1 | 3 | 4 | D | Ca 0 |
| 57 | `actions/take_person.py` | 91 | 73 | 0 | 2 | 1 | 5 | 12 | D | CC 12 `choose`; Ca 0 |
| 58 | `actions/wait_page.py` | 82 | 72 | 0 | 3 | 1 | 3 | 18 | D | CC 18 `execute`; 1 fn >30 LOC; Ca 0 |
| 59 | `actions/base.py` | 92 | 71 | 1 | 1 | 2 | 7 | 5 | D | — |
| 60 | `core/result.py` | 105 | 69 | 10 | 0 | 3 | 12 | 2 | — | — |
| 61 | `actions/click_send.py` | 81 | 69 | 0 | 4 | 1 | 3 | 4 | D | Ca 0 |
| 62 | `core/interfaces.py` | 113 | 66 | 0 | 0 | 8 | 24 | 1 | — | Ca 0 |
| 63 | `stores/atomic.py` | 82 | 65 | 3 | 1 | 1 | 7 | 5 | B | — |
| 64 | `stores/session_store.py` | 79 | 60 | 1 | 1 | 1 | 7 | 4 | B | — |
| 65 | `core/di.py` | 67 | 54 | 2 | 0 | 1 | 7 | 4 | — | — |
| 66 | `actions/click_back.py` | 62 | 54 | 0 | 3 | 1 | 3 | 2 | D | Ca 0 |
| 67 | `actions/click_main_tab.py` | 62 | 54 | 0 | 3 | 1 | 3 | 2 | D | Ca 0 |
| 68 | `app/lifecycle.py` | 62 | 54 | 1 | 0 | 1 | 5 | 9 | — | — |
| 69 | `services/run/state_machine.py` | 68 | 53 | 1 | 0 | 2 | 9 | 3 | C | — |
| 70 | `actions/type_message.py` | 62 | 52 | 0 | 3 | 1 | 3 | 10 | D | Ca 0 |
| 71 | `actions/context.py` | 78 | 50 | 0 | 0 | 1 | 6 | 4 | D | Ca 0 |
| 72 | `stores/block_store.py` | 62 | 48 | 1 | 2 | 1 | 8 | 9 | B | — |
| 73 | `stores/jsonio.py` | 66 | 48 | 7 | 0 | 0 | 0 | 6 | B | — |
| 74 | `stores/labels_file_store.py` | 60 | 45 | 1 | 1 | 1 | 6 | 3 | B | — |
| 75 | `stores/undo_store.py` | 57 | 45 | 1 | 2 | 1 | 4 | 5 | B | — |
| 76 | `services/history/__init__.py` | 48 | 41 | 3 | 7 | 1 | 1 | 3 | C | Ce 7 |
| 77 | `main.py` | 49 | 39 | 0 | 4 | 0 | 0 | 2 | — | — |
| 78 | `app/bootstrap.py` | 42 | 36 | 1 | 9 | 0 | 0 | 2 | — | Ce 9 |
| 79 | `stores/bookmark_store.py` | 45 | 35 | 1 | 2 | 1 | 5 | 4 | B | — |
| 80 | `actions/search_users.py` | 41 | 33 | 0 | 3 | 1 | 3 | 3 | D | Ca 0 |
| 81 | `actions/repeat_loop.py` | 39 | 30 | 0 | 2 | 1 | 3 | 2 | D | Ca 0 |
| 82 | `backend/action_engine.py` | 33 | 29 | 0 | 2 | 0 | 0 | 2 | D | Ca 0 |
| 83 | `actions/pause.py` | 33 | 26 | 0 | 2 | 1 | 3 | 3 | D | Ca 0 |
| 84 | `backend/logger.py` | 33 | 25 | 1 | 0 | 0 | 0 | 1 | D | — |
| 85 | `actions/conditional_skip.py` | 30 | 23 | 0 | 2 | 1 | 2 | 2 | D | Ca 0 |
| 86 | `services/run/__init__.py` | 22 | 19 | 7 | 1 | 0 | 0 | 3 | C | — |
| 87 | `services/run_service/__init__.py` | 19 | 16 | 0 | 1 | 0 | 0 | 2 | C | — |
| 88 | `actions/find_click_runner.py` | 15 | 12 | 3 | 1 | 0 | 0 | 0 | D | — |
| 89 | `actions/__init__.py` | 15 | 11 | 1 | 1 | 0 | 0 | 0 | D | — |
| 90 | `backend/bridge.py` | 12 | 9 | 1 | 2 | 0 | 0 | 0 | D | — |
| 91 | `core/__init__.py` | 11 | 8 | 0 | 3 | 0 | 0 | 0 | — | — |
| 92 | `actions/base_action.py` | 10 | 8 | 19 | 2 | 0 | 0 | 0 | D | — |
| 93 | `backend/db_manager.py` | 9 | 7 | 0 | 1 | 0 | 0 | 0 | D | Ca 0; compat shim |
| 94 | `backend/history_service.py` | 9 | 7 | 0 | 1 | 0 | 0 | 0 | D | Ca 0; compat shim |
| 95 | `backend/label_store.py` | 9 | 7 | 0 | 1 | 0 | 0 | 0 | D | Ca 0; compat shim |
| 96 | `bridge/__init__.py` | 8 | 7 | 0 | 0 | 0 | 0 | 0 | — | — |
| 97 | `stores/__init__.py` | 10 | 7 | 0 | 1 | 0 | 0 | 0 | B | — |
| 98 | `backend/collector.py` | 7 | 5 | 0 | 1 | 0 | 0 | 0 | D | Ca 0; compat shim |
| 99 | `backend/history_db.py` | 7 | 5 | 0 | 1 | 0 | 0 | 0 | D | Ca 0; compat shim |
| 100 | `backend/history_models.py` | 6 | 5 | 0 | 1 | 0 | 0 | 0 | D | Ca 0; compat shim |
| 101 | `app/__init__.py` | 6 | 5 | 0 | 0 | 0 | 0 | 0 | — | — |
| 102 | `services/__init__.py` | 5 | 4 | 2 | 0 | 0 | 0 | 0 | C | — |
| 103 | `backend/history_repo.py` | 5 | 3 | 0 | 1 | 0 | 0 | 0 | D | Ca 0; compat shim |
| 104 | `backend/media_store.py` | 5 | 3 | 0 | 1 | 0 | 0 | 0 | D | Ca 0; compat shim |
| 105 | `backend/preset_store.py` | 5 | 3 | 0 | 1 | 0 | 0 | 0 | D | Ca 0; compat shim |
| 106 | `backend/user_memory.py` | 5 | 3 | 0 | 1 | 0 | 0 | 0 | D | Ca 0; compat shim |
| 107 | `services/history_service/__init__.py` | 1 | 1 | 0 | 1 | 0 | 0 | 0 | C | — |
| 108 | `backend/__init__.py` | 1 | 0 | 3 | 0 | 0 | 0 | 0 | D | compat shim |

### 12.1 Dead-code findings (vulture ≥ 60 %)

201 findings: 134 unused methods, 28 classes, 11 variables, 10 properties,
9 attributes, 8 functions, 1 import. The 5 at 100 % confidence (safe deletion —
AREA D, P3-8):

```
services/run/coordinator.py:53: unused variable 'scroll_parser'   (100 %)
services/run/hooks.py:68:       unused variable 'coordinator'     (100 %)
services/run/hooks.py:71:       unused variable 'coordinator'     (100 %)
services/run/hooks.py:74:       unused variable 'coordinator'     (100 %)
backend/cdp_client.py:35:       unused variables exc_type, tb     (100 %)
```

Notable 60 %-confidence items per area:

| area | finding |
|---|---|
| B | `history_repo.possible_duplicates`, `label_store.{by_name,assignments,ids_for,labels_for,is_bound}`, `media_store.{get_by_url,retry_failed,clear_cache}`, `user_memory.{upsert_many,count_unmessaged}`, `history_db.{LATE_COLUMNS,_add_missing_columns}`, `preset_store.dirty`, `block_store.{save_custom_block,delete_custom_block}`, `labels_file_store.dirty`, `session_store.{LEGACY_KEYS,dirty}`, `settings_store.dirty` |
| C | `collector_service.{on_run_started,on_run_finished}`, `history/export.export_chat`, `history/query.SETTING_KEYS`, `history/mutate.row_factory`, `run/__init__.__getattr__` |
| D | 5 × 100 %-confidence dead symbols (§4.4); `core/result.{map,of,aof}` — frozen, do not delete |
