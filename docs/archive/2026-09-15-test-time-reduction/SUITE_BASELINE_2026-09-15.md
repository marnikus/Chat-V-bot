# Suite baseline — raw measurements (2026-09-15)

Data behind `TEST_TIME_REDUCTION_PLAN_2026-09-15.md` (same folder). Everything
here was run on the branch state of 2026-09-15, unmodified tree.

## 1. Environment

| Item | Value |
|---|---|
| Machine | sandbox, **2 CPU cores** (`nproc` = 2), Python 3.11.2 |
| Deps | throwaway venv: PySide6 6.11.2, pytest 9.1.1, pytest-asyncio 1.4.0, pytest-xdist 3.8.0, coverage 7.x; aiosqlite / websockets / qasync / aiohttp from `requirements.txt` |
| Qt headless | `QT_QPA_PLATFORM=offscreen`, GL/NSS/dbus stubs built by `tools/build_stubs.py <venv> /tmp/stublibs`, `LD_LIBRARY_PATH=/tmp/stublibs` (documented in SYSTEM_OF_RECORD.md §7) |
| Node | v22.22.3 |

## 2. Commands used

```bash
export QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs
PY=/tmp/pt/bin/python

# collection
$PY -m pytest -q --collect-only | tail -3          # 3176 tests collected in 2.17s

# full serial suite (≈ CI test-suite job)
time $PY -m pytest tests -q --deselect tests/test_sash_webengine.py --durations=40

# group timings
time $PY -m pytest tests/unit -q
time $PY -m pytest tests/integration -q
time $PY -m pytest tests -q --ignore=tests/unit --ignore=tests/integration \
     --deselect tests/test_sash_webengine.py

# parallel safety probe — zero tree changes
time $PY -m pytest tests -q -n 2 --dist loadfile --deselect tests/test_sash_webengine.py

# coverage gate, the RULE 16 §16.3 command verbatim (serial)
time $PY -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
$PY -m coverage json -o /tmp/coverage.json

# node harness
for f in tests/test_*.js; do node "$f"; done       # all green
```

## 3. Headline results

| Run | Result | Wall | User CPU |
|---|---|---:|---:|
| Full serial | **3168 passed, 6 skipped, 1 deselected, 1 xfailed, 902 subtests** | 367.4 s | 115.6 s |
| Full `-n 2 --dist loadfile` | identical, **0 failures** | 181.5 s | 114.8 s |
| Coverage-gate serial | identical + line 91.77 %, branch 88.03 % | 519.2 s | 266.3 s |
| `tests/unit` | 1049 passed, 2 skipped, 1 xfailed, 897 subtests | 55.2 s | 8.2 s |
| `tests/integration` | 603 passed | 46.5 s | 20.5 s |
| Root files (82) | 1516 passed, 4 skipped | 261.7 s | 85.3 s |
| Single small file (`test_criteria_engine.py`) | 9 passed | 0.73 s | — |
| 29 node suites, sequential | 0 failures | 7.7 s total | — |

Derived: wall/CPU = 2.7× (wait-bound overall), 6.7× on `tests/unit`.
xdist gain: −50.6 % wall on 2 cores. Coverage overhead: +41.3 % vs plain run.
Pyramid shares of Python tests: unit 33.1 %, integration 19.0 %, root 47.8 %.

## 4. Slowest 15 tests (from `--durations=40`, serial run)

| s | Test |
|---:|---|
| 22.50 | `test_rule16_new_code.py::TestCloneBaselineIsHonest::test_no_new_clone_groups_and_no_stale_baseline_entries` |
| 15.03 | `unit/services/test_world_events.py::TestRunWhenWorldOpen::test_a_world_that_never_opens_still_reports_itself` |
| 6.58 | `test_world_write_gate.py::TestTrashLifecycle::test_a_dropped_step_cannot_be_undone_into_a_success` |
| 4.36 | `test_chat_parser_delta.py::TestSyncScenarios::test_scroll_that_empties_the_pane_is_retried_not_marked_done` |
| 4.29 | `test_world_write_gate.py::TestUndoProvesItself::test_a_refused_undo_reports_and_stays_retryable` |
| 3.48 | `test_db_manager.py::TestDbBridge::test_a_delete_is_not_an_undo_step` |
| 3.31 | `test_world_write_gate.py::TestUndoProvesItself::test_clear_history_undo_reports_the_messages_it_restored` |
| 3.28 | `test_world_write_gate.py::TestUndoProvesItself::test_redo_hides_them_again_and_says_so` |
| 2.45 | `test_world_write_gate.py::TestUndoProvesItself::test_delete_then_undo_restores_person_and_history` |
| 2.44 | `test_world_write_gate.py::TestTrashLifecycle::test_a_step_that_falls_off_the_timeline_gives_up_its_data` |
| 2.42 | `test_world_write_gate.py::TestTrashLifecycle::test_opening_the_world_again_erases_the_trash` |
| 2.42 | `test_world_write_gate.py::TestTrashLifecycle::test_while_the_session_runs_a_delete_is_fully_reversible` |
| 2.41 | `test_world_write_gate.py::TestUndoProvesItself::test_the_db_window_is_told_about_every_change` |
| 2.11 | `unit/actions/test_block_base.py::test_every_click_block_passes_the_engine_through` |
| 2.01 | `unit/actions/test_block_actions_coverage.py::TestMarkMessaged::test_status_matrix` |

## 5. File-level timings (standalone serial runs, include ~1 s startup each)

| File | Tests | Wall |
|---|---:|---:|
| `tests/test_world_write_gate.py` | 43 | 41.5 s |
| `tests/test_rule16_new_code.py` | 19 (+4 skipped) | 23.9 s |
| `tests/test_recollect_after_clear.py` | 20 | 21.0 s |
| `tests/test_db_manager.py` | 42 | 17.7 s |
| `tests/unit/services/test_world_events.py` | 14 | 15.4 s |
| `tests/test_history_bridge.py` | 27 | 11.4 s |
| `tests/test_userdb_sort_bridge.py` | 6 | 8.6 s |
| `tests/unit/actions/test_block_actions_coverage.py` | 39 | 6.4 s |
| `tests/test_media_recovery_e2e.py` | 12 | 5.5 s |
| `tests/test_db_switch_e2e.py` | 2 | 2.1 s |

Sum ≈ 153.5 s ≈ 40 % of the serial suite. Node harness slowest:
`test_history_agent_js.js` 3.4 s, `test_history_panels_boot.js` 1.9 s; the
other 27 suites are ≤ 0.8 s each.

## 6. Sleep census (grep, 2026-09-15)

`asyncio.sleep` occurrences in `tests/**/*.py`: **127** across ~35 files.
Densest (occurrences): `unit/actions/test_wait_page_cancellation.py` (9),
`unit/actions/test_find_click_blocks.py` (9), `unit/actions/test_speed_multiplier.py` (8),
`test_world_write_gate.py` (7), `integration/services/test_services_run.py` (7),
`integration/services/test_undo_support_contract.py` (6),
`integration/run_safety/test_stop_contract.py` (6),
`integration/run_safety/test_cleanup_contract.py` (6),
`unit/actions/test_click_user_tab_verify.py` (5),
`test_live_status_and_order.py` (5), `test_collect_visual_and_live_refresh.py` (5),
`integration/services/test_services_history.py` (5).
`time.sleep`: 7 occurrences, all in the deselected `test_sash_webengine.py`.

Representative mechanism (the 15 s test): `wait_for_world_open` /
`run_when_world_open` poll with real `asyncio.sleep(step)`; the never-opens
report is verified by living through the real production grace. The same file
already demonstrates the fix pattern: `timeout=0.1, step=0.01`.

## 7. Suite composition and doc drift

| Bucket | Files | Tests |
|---|---:|---:|
| `tests/test_*.py` (root, unclassified) | 82 | 1,516 |
| `tests/unit/` | 57 | 1,049 |
| `tests/integration/` | 40 | 603 |
| Node harness `tests/test_*.js` | 29 | 0 failures (stand-alone) |

SYSTEM_OF_RECORD.md §7 still says "2829 tests + 894 subtests" and "27 Node
harness files" — the counts were refreshed in §7 on 2026-09-15; the
marker-based invocation replaces the hand deselect when W1 lands (RULE 17).

Markers registered today: **none** (only `parametrize` used; `--strict-markers`
on). `pytest-asyncio` is installed but has no `asyncio_mode` config and no
`asyncio` markers — async tests run via `unittest.IsolatedAsyncioTestCase`.

CI: `tools/ci/quality-gate.yml` is **not active** (header inside the file
documents the `workflows`-permission refusal and the manual copy step).
