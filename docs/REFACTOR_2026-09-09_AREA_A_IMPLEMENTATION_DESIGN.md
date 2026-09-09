# AREA A — Startup & Test Harness Implementation Design

**Date:** 2026-09-09
**Branch base:** `arena/01a08849-chat-v-bot`
**Plan source:** `docs/REFACTOR_2026-09-09_FOUR_AREA_PLAN.md` §6.1 / §5 (P0-1 … P0-7)
**Status:** design → tests-first implementation

---

## 1. Scope

This document is the design for **AREA A only** from the four-area plan. It
makes `pytest tests` collect cleanly, stops the two test-harness `sys.modules`
poisoners, retargets one stale test, and fixes the two production NameErrors
that keep the run engine from loading a stack. No production behaviour changes
beyond those two missing imports.

### In scope

| kind | file | change |
|---|---|---|
| production | `services/run/coordinator.py` | import `BaseAction, get_action_class` (P0-1) |
| production | `services/run/progress.py` | runtime `UserRecord` import + fallback (P0-2) |
| test infra | `tests/integration/services/test_run_service_paths.py` | remove Qt stub block (P0-3) |
| test infra | `tests/test_main_entry.py` | scope Qt stubs; keep only non-`main`-attribute tests (P0-4, P0-7) |
| test infra | `tests/test_stores_migration_rollback.py` | retarget to `stores.migration.migrate_legacy_config` (P0-6) |
| test infra | `tests/conftest.py` (new) | repo path; seed real Qt/run/engine/bridge; teardown poison check (P0-5) |
| test infra | `tests/unit/app/` (new) | relocated `main.*` contract tests for `app.bootstrap`/`app.window` (P0-7) |
| config | `pytest.ini` (new) | test discovery / strict markers / warning filters |

Out of scope: `stores/`, `services/**` besides the two files above, `backend/**`,
`actions/**`, `bridge/**`, `app/**` production code, `core/**`, `main.py`.

---

## 2. Problems (from the plan, re-measured on this checkout)

| # | problem | evidence | result before fix |
|---|---|---|---|
| P0-1 | `RunCoordinator.load_stack` cannot resolve action classes | `coordinator.py:42` calls `get_action_class(...)`; never imported | `NameError` on every stack load |
| P0-2 | `RunProgress` cannot construct/use `UserRecord` at runtime | `progress.py:10` imports it only under `TYPE_CHECKING`; `_run_single_target_cycle` calls `UserRecord(nick=...)` | runtime `NameError` in single-target cycles |
| P0-3 | `tests/test_run_service_paths.py` replaces `PySide6` + `PySide6.QtCore` at module import | `sys.modules.update(...)` lines 12–26 | 14 collection errors (`object.__init__()` TypeError in `bridge.router._meta_members`) in this checkout |
| P0-4 | `tests/test_main_entry.py` installs Qt stubs at module level | `_install_qt_stubs()` called at line 333; never undone | second, wider poisoning point |
| P0-5 | un-importable test modules caused by P0-3 | 14 identical `bridge/router.py` collection errors | blocks ~24 test modules in this checkout |
| P0-6 | `tests/test_stores_migration_rollback.py` imports an API that does not exist | `from stores.migration import migrate, needs_migration`; module only has `migrate_legacy_config` | 1 collection error |
| P0-7 | `test_main_entry.py` still targets moved symbols | `main.MainWindow`, `main.build_container`, `main._queue_path` no longer exist | 23 stale `main.*` test failures |

Measured with real PySide6 (installed in `.venv`, headless shims built by
`tools/build_stubs.py`):

```
python -m pytest tests -p no:cacheprovider --continue-on-collection-errors
# baseline on this checkout: 325 failed, 1035 passed, 2 skipped, 1 xfailed, 14 errors
```

Because PySide6 is real in this checkout, the poisoner effects are slightly
different from the paper plan's numbers. The 14 collection errors here are
exactly the P0-3 symptom: `tests/test_run_service_paths.py` replaces QtCore with
a pass-through `_QObject`, then the later `bridge.router` import builds against
that fake class and raises `object.__init__() takes exactly one argument`.

---

## 3. Target structure

```
pytest.ini                          # new
tests/
  conftest.py                       # new — repo path, seed real Qt, teardown poison check
  integration/services/test_run_service_paths.py   # stub block removed + new P0-1/P0-2 tests
  test_main_entry.py                # scoped stubs; only main/misc + registry + DB tests remain
  test_stores_migration_rollback.py # retargeted to migrate_legacy_config
  unit/app/
    qt_stubs.py                     # new — scoped Qt/fake-class context manager
    test_app_bootstrap.py           # new — relocated `queue_path`/`create_container` tests
    test_app_window.py              # new — relocated `MainWindow` geometry/close tests
    test_harness_no_qt_poison.py    # new — Gate 1-style poison regression check
```

### 3.1 Why a scoped-stub helper

`app.window.MainWindow` and `main.main()` need Qt widgets that cannot be created
headless (`QWebEngineView` aborts without a real GL/display). Those two domains
therefore keep lightweight fakes. The fakes are installed only inside a test via
`unittest.mock.patch.dict(sys.modules, ...)` and removed before teardown, so no
other module ever sees a fake `PySide6.QtCore`.

`tests/conftest.py` imports real `import main`-level modules *before* any stub
is used; this seeds `services.run`, `app.bootstrap`, and `bridge.router` with
real PySide6 classes and also makes `bridge.router` collection-safe.

### 3.2 Test ownership

All new/edited files in this area are disjoint from B/C/D files. The only test
files touched are the three Area-A files plus the new `tests/unit/app/` tree.

---

## 4. Production changes (tests-first)

### 4.1 `services/run/coordinator.py`

Add near the existing imports:

```python
from actions.base_action import BaseAction, get_action_class
```

This is the only production edit in the file. `BaseAction` already re-exports
`get_action_class` from `actions/registry`.

### 4.2 `services/run/progress.py`

Replace `if TYPE_CHECKING: from stores.user_memory import UserRecord` with the
same runtime import + fallback pattern already used in `coordinator.py`:

```python
try:
    from stores.user_memory import UserRecord
except Exception:  # keep the engine usable if the store shim is unavailable
    from dataclasses import dataclass

    @dataclass
    class UserRecord:
        nick: str
        messaged: bool = False
```

`RunQueueMixin._run_single_target_cycle` therefore constructs a real `UserRecord`
at runtime instead of raising `NameError`.

---

## 5. Test plan

### 5.1 `tests/integration/services/test_run_service_paths.py`

- **Delete** the `if "PySide6" not in sys.modules:` stub block (P0-3).
- Keep the sys-path insert (so the file also works when run directly).
- **Add** `TestRunCoordinatorLoadStack`:
  - a known `PAUSE` block is instantiated and returned by `get_stack()`;
  - unknown `block_id` values are dropped;
  - non-dict and `None` items are dropped;
  - `enabled` defaults to `True`.
- **Add** `TestRunProgressUserRecord`:
  - `services.run.progress.UserRecord` is importable at runtime;
  - constructing `UserRecord(nick="x")` and round-tripping works.
  These are the red-before / green-after regression pins for P0-1 / P0-2.

### 5.2 `tests/unit/app/qt_stubs.py`

Move the fake Qt classes out of `test_main_entry.py` into a reusable helper.
Exposes:

- the existing fake `QObject`, `Signal`, `QTimer`, `QMainWindow`,
  `QWebEngineView`, `QWebChannel`, `QUrl`, `QEventLoop`, `QApplication`, etc.;
- `stub_qt()` — context manager via `mock.patch.dict(sys.modules, ...)`;
- `load_main()` — pops `main`, `app.bootstrap`, `app.window`, `app.lifecycle`
  inside `stub_qt()` and imports `main` under stubs.

### 5.3 `tests/unit/app/test_app_bootstrap.py`

Relocate the 8 bootstrap/wiring tests from `test_main_entry.py`:

- `TestQueuePath` (4 tests) → `app.bootstrap.queue_path`.
- `TestBuildContainer` (4 tests) → `app.bootstrap.create_container`.

### 5.4 `tests/unit/app/test_app_window.py`

Relocate the 15 `TestMainWindowGeometryAndClose` tests → `app.window.MainWindow`.
The module is reloaded inside `stub_qt()` so `QWebEngineView` never needs a
real display; stubs are scoped to this item.

### 5.5 `tests/test_main_entry.py`

- Keep the fake-class definitions but **remove the module-level
  `_install_qt_stubs()` call**.
- Keep only:
  - `TestRegistryScanOnEnginePath` (2 tests),
  - `TestMainSmokeStartExit` (3 tests),
  - `TestDbInitContract` (1 test).
- Every test that needs `main` uses `load_main()` from `qt_stubs` (scoped).
- Remove `TestQueuePath`, `TestBuildContainer`, and
  `TestMainWindowGeometryAndClose` (moved to §5.3/§5.4).

### 5.6 `tests/test_stores_migration_rollback.py`

Retarget to the actual public function
`stores.migration.migrate_legacy_config(legacy_path, config_dir) -> bool`.
New contract:

- missing legacy → `False`, no config files, no archive;
- legacy-only → `True`, writes the seven store files, archives the legacy
  `config.json` as `config.json.migrated-<timestamp>` (not deleted);
- existing store files → `False`, existing files untouched;
- corrupt legacy → `False`, legacy file preserved, no archive;
- non-dict legacy → `False`;
- migration is idempotent after the first run;
- archived file is byte-for-byte the original (`rollback` property);
- each section lands in the right file (settings/bookmarks/blocks/presets/
  labels/session/undo);
- unchanged legacy sections survive key-for-key.

### 5.7 `tests/conftest.py`

- insert repo root on `sys.path`;
- assert `PySide6.QtCore.QObject` is the real PySide6 class (fail fast at
  collection if a poisoner returns);
- import real `services.run`, `app.bootstrap`, and `main` once so common
  modules are cached against real Qt and `bridge.router` is collection-safe;
- `pytest_runtest_teardown` re-checks `QObject` and raises a clear error if any
  test left PySide6 stubbed in `sys.modules`.

### 5.8 `tests/unit/app/test_harness_no_qt_poison.py`

Gate-1 style regression:

- import `tests.test_main_entry` and
  `tests.integration.services.test_run_service_paths`;
- assert `sys.modules["PySide6.QtCore"].QObject` is still real PySide6.

### 5.9 `pytest.ini`

```ini
[pytest]
testpaths = tests
addopts = -p no:cacheprovider --strict-markers
filterwarnings =
    ignore::DeprecationWarning
```

---

## 6. Exit criteria

> **Note on the plan's Gate 2 example.** The plan writes
> `{"block_id": "pause", "id": "A"}`. Block ids in this codebase are uppercase
> (`PAUSE`, `CLICK_USER`, …) and `ActionRegistry.get()` is case-sensitive, so
> the literal lowercase example loads an empty stack. AREA A does not alter
> registry casing; the regression test in §5.1 uses the real `PAUSE` id and
> asserts the stack is non-empty.

1. `python -m pytest tests -q -p no:cacheprovider` collects **0 errors**.
2. `import main` succeeds headless.
3. `RunCoordinator(cdp=None, memory=None, criteria=None).load_stack(
   [{"block_id": "pause", "id": "A"}])` returns without raising.
4. `services.run.progress.UserRecord` is importable and constructible.
5. No Qt poisoning: `tests/conftest.py` teardown check is green for every test.
6. Full suite failure count does not regress versus the pre-Area-A baseline, and
   the Area-A owned files are green.

---

## 7. Risks / boundaries

- `tests/unit/app/qt_stubs.py` is a new helper living under `tests/unit/app/`.
  It is not production code and is not imported by any B/C/D owned test.
- `tests/conftest.py` importing `main` uses real Qt. On a truly display-less
  CI it still works headless when PySide6's native libs can be imported (the
  repository's documented sandbox uses `tools/build_stubs.py` + `QT_QPA_PLATFORM=offscreen`).
- No `bridge/*`, `app/*`, `main.py`, `stores/*`, `backend/*`, or `actions/*`
  production file is edited.
