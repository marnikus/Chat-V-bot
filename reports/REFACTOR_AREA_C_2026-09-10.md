# Area C implementation and validation — 2026-09-10

## Result

Area C service decomposition is implemented. Production changes are confined to
`services/`; `services/run/coordinator.py` and `services/run/progress.py` remain
untouched. Stores, backend, actions, bridges, core, app, main, and Area A's test
files were not edited.

**145 new tests pass.** The comparable broad suite improves from **52 failures
to 48**, with **no new failing test IDs**. The remaining failures are not hidden
or marked xfail by this change. This is not a claim that the whole repository
is green or that coverage is 100%.

Design written before production changes:
[`REFACTOR_AREA_C_DESIGN_2026-09-10.md`](../docs/REFACTOR_AREA_C_DESIGN_2026-09-10.md).

## Implementation

| Surface | Internal structure | Compatibility |
|---|---|---|
| Collector | `collector/probe.py` (`CollectorProbe`), `collector/archive.py` (`CollectorArchive`), `collector/state.py` | Original QObject, signals, lifecycle/busy guards, private gate, cursor comparison, backfill, media draining and payloads retained |
| Undo | `undo/projection.py` (`UndoProjection`), `undo/world_store.py` (`UndoWorldStore`) | One facade-owned timeline, same sequence IDs and app/world persistence formats; command application stays on `UndoService` |
| Database | `db/registry.py` (`DbRegistry`), `db/lifecycle.py` (`DbLifecycle`), `db/paths.py` | `DbManager` facade, helper exports, load/switch/rollback and reversible-clean contracts retained |
| History | `history/binding.py`, `history/lifecycle.py`, `history/migration.py`, small format renderer in `history/export.py` | Methods remain accessible on `HistoryService` and `HistoryExportService`; query/mutate APIs unchanged |
| Status forwarding | `status_events.py` (`StatusEvents`) | Identical EventBus log forwarding shared by CDP, people and undo services |
| Run state | Explicit idle-to-paused transition | Pause before Run is valid; starting still clears stale pause |

LayoutService was inspected: it is a pure validator/normalizer and has **no**
status-forwarding method to extract. Adding a bus dependency there solely to
match the plan's grouping would introduce needless coupling.

### Behavioral repairs pinned by tests

1. **Pause before start:** allow `idle -> paused`.
2. **All-disabled stack:** return `skip`, not successful user completion.
3. **Undo branch truncation:** persist truncation even when the new value equals
   the value at the undo pointer; the old redo tail must not survive.
4. **Create-path containment:** sanitize the create *name* before resolution;
   explicit paths continue to be supported by load/restore.

The first three had new failing contracts before production edits. The fourth
was already reproduced by two existing Area C tests in the baseline.

### Alias cleanup and boundary limitation

* Repointed Area C-owned imports to `services.history` / `services.run`.
* Deleted `services/history_service/__init__.py`.
* **Retained `services/run_service/__init__.py`** because the remaining importer
  is `tests/integration/services/test_run_service_paths.py`, expressly owned by
  Area A under §6.5. Backend shims already use canonical imports on this checkout.
  Removing the shim now would break that test; repointing it would violate the
  Area C-only boundary. This final deletion remains dependent on Area A.

## Test-first evidence

| Stage | Passed | Failed | Notes |
|---|---:|---:|---|
| Focused existing-service baseline, unchanged production | 357 | 10 | Run before extraction |
| New pre-refactor contracts, unchanged production | 118 | 3 | All three failures reproduced intended service repairs |
| Final new contracts + structural/API guards | **145** | **0** | 121 initial cases, 15 additional run branch cases, 9 boundary guards |
| Broad baseline from a disposable `git archive HEAD` copy | 1,551 | 52 | 1 skipped, 1 existing xfail |
| Final broad suite | **1,700** | **48** | 1 skipped, 1 existing xfail; no new failing IDs |

The same broad-suite exclusions were used for both baselines and final runs:

* `tests/integration/services/test_run_service_paths.py`: Area A's global Qt stub poisoner.
* `tests/test_main_entry.py`: Area A's second global Qt stub poisoner / stale entrypoint contracts.
* `tests/test_stores_migration_rollback.py`: Area A's stale migration imports.
* `tests/test_sash_webengine.py`: real QtWebEngine/display test is unsupported in this sandbox.

The one skip is the existing test requiring a local, untracked “Tab Main”
custom preset. A repeat run with suite-generated `config/blocks.json` present
produced one extra `StopIteration` in that test. Preserving the generated files
outside the checkout and rerunning from the original clean runtime state
restored the comparable **48-failure** result. No test was weakened to hide it.

Two warnings remain in the final broad run: an existing history-binding test
creates an unawaited coroutine, and an aiosqlite worker can outlive a failing
test's event loop. They are not counted as passes or production fixes.

### Four existing failures resolved

* `TestPauseResume::test_a_new_run_clears_a_stale_pause`
* `TestRunGuards::test_all_disabled_runs_nothing_and_marks_nobody`
* `TestCreateContainment::test_create_with_a_traversal_name_stays_inside_the_root`
* `TestCreateContainment::test_create_with_an_absolute_name_stays_inside_the_root`

The remaining failure IDs match the baseline. They include the missing
`get_action_class` / runtime `UserRecord` imports in Area A's run files, the
paused-stop reporting assertion in the unchanged coordinator, Area B's
small-store constructor and bookmark contracts, and pre-existing action/UI
contract mismatches. Area C-owned integration tests that reach those defects
still fail; ownership of a test does not authorize editing another area's
production files.

## Coverage and complexity

Coverage measured with branches enabled over **all of `services`**, including
Area A's unchanged files, compatibility code, and every extracted module.
Line and branch percentages below are separate (pytest's combined percentage
is not mislabeled as line coverage).

| Scope | Lines | Branches |
|---|---:|---:|
| **All services** | **90.26%** (2,585 / 2,864) | **85.39%** (760 / 890) |
| `undo_service.py` | **82.55%** | 71.77% |
| `undo/projection.py` | 94.85% | 90.48% |
| `undo/world_store.py` | 88.57% | 80.00% |
| `collector_service.py` | 89.74% | 87.50% |
| `collector/probe.py` | 100.00% | 96.15% |
| `collector/archive.py` | 94.67% | 92.86% |
| `run/state_machine.py` | 100.00% | 100.00% |
| `run/hooks.py` | 100.00% | 100.00% |
| `run/error_recovery.py` | 100.00% | 100.00% |

* `Collector._tick`: **CC 5**, **17 physical source lines** (target CC <=15 / <=60 lines).
* `UndoProjection.migrate_global_history`: **CC 7** (target <=10).
* **105 public signatures** compared with the unchanged baseline and retained
  as a regression fixture; all match.
* AST import comparison: **zero added `backend.*` dependencies**.
* New/extracted-code undefined-name and unused-import checks: clean.
* `git diff --check`: clean.

## Mutation check

A reproducible, explicit operator-set runner is provided in
`tests/area_c_mutation.py`. It copies sources to a temporary directory and runs
one fresh pytest process per mutant, never modifying the working checkout.

Scope: the three **C-owned** run modules, not Area A's coordinator/progress.
All eligible sites for the documented operators were tested; this was not a
random sample and equivalent survivors were not discounted.

| Module | Killed | Survived |
|---|---:|---:|
| `state_machine.py` | 16 | 3 |
| `hooks.py` | 39 | 18 |
| `error_recovery.py` | 52 | 37 |
| **Total** | **107** | **58** |

**107 / 165 = 64.85%**, zero timeouts, zero infrastructure errors. This clears
60% for the combined C-owned scope. It is **not** a full-package mutmut score;
individual error-recovery mutation coverage is 58.43%, and the plan's literal
whole-`services/run/*` score still requires the Area A merge and joint validation.
Survivors remain, notably some log/event deletions and fallback/default choices;
100% line/branch execution does not imply that every mutation is detected.

## Reproduction

Python 3.11, real PySide6 (no global stubs), Qt offscreen. Dependencies installed
in the ignored repository `.venv`:

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt pytest pytest-asyncio pytest-cov radon ruff

QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_area_c_contracts.py tests/test_area_c_run_contracts.py \
  tests/test_area_c_structure.py -q

# Use a pristine checkout/runtime state for comparable whole-suite numbers.
COVERAGE_FILE=/tmp/area-c.coverage QT_QPA_PLATFORM=offscreen \
.venv/bin/python -m pytest tests \
  --ignore=tests/integration/services/test_run_service_paths.py \
  --ignore=tests/test_main_entry.py \
  --ignore=tests/test_stores_migration_rollback.py \
  --ignore=tests/test_sash_webengine.py \
  --cov=services --cov-branch --cov-report=term-missing -q

.venv/bin/python tests/area_c_mutation.py --output /tmp/area-c-mutations.json
.venv/bin/python -m radon cc services/collector_service.py services/undo/projection.py -s
git diff --check
```

Raw baseline/final logs, coverage JSON and mutation details are preserved in
`/home/user/area-c-results/`, outside Git. No database, runtime config, coverage
binary, virtual environment, or generated mutation source tree is added to Git.
