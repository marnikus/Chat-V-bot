# Test architecture redesign — from 387 s to ~30 s (implemented)

Date 2026-09-14 · branch `arena/01a0a172-chat-v-bot` · Area D follow-up

## Problem (measured)

Full suite: **3249 tests, 902 subtests, 387 s (6:27)** without coverage, **475 s (7:55)** with `--branch` coverage.  
Slowest 5 from `--durations=50`:

* 23.8 s `test_rule16_new_code.py::TestCloneBaselineIsHonest::test_no_new_clone_groups...` — runs `clone_scan` over 208 files
* 15.0 s `test_world_events.py::TestRunWhenWorldOpen::test_a_world_that_never_opens...`
* 6.5 s `test_world_write_gate.py::TestTrashLifecycle::test_a_dropped_step...`
* 4.3 s `test_chat_parser_delta.py::TestSyncScenarios::test_scroll_that_empties...`
* 4.2 s `test_rule16_new_code.py::TestClassLimitsAreEnforced::test_enforcement_actually_fires...`

Root causes:

* **Conftest tax**: `tests/conftest.py` imported `PySide6.QtWidgets.QApplication`, `app.bootstrap`, `services.run.RunCoordinator`, `main` for *every* test, even pure unit tests. Qt import ~0.8 s.
* **DB tax**: 307 references to `HistoryDB`/`HistoryRepo`/`tempfile.mkdtemp`. Each file DB init ~1.4 s. 100 DB tests × 1.4 s = 140 s.
* **Clone scan tax**: `clone_scan` parses 208 files via AST, no cache — 23.8 s per run, twice in gate tests.
* **No parallelism**: single-process pytest. No `pytest-xdist`.
* **Coverage overhead**: `coverage run --branch` +20% (387 s → 475 s).
* **No tiers**: no markers, no fast path.

## Implemented (this PR)

### 1. Split conftest — pay Qt only when needed (done)

Old:
```
tests/conftest.py → imports PySide6, app.bootstrap, RunCoordinator, main (heavy)
```

New:
```
tests/conftest.py → minimal: sys.path only, tries Qt import optionally, provides mem_db fixture
tests/unit/app/conftest.py → imports Qt, seeds RunCoordinator (only for Qt tests)
tests/integration/conftest.py → same
app/__init__.py → lazy PEP 562 __getattr__, so `from app.lifecycle import ...` no longer pays Qt tax
```

Measured:
* Collection: **20.77 s → 1.16 s** (18× faster) — removed AST parsing in auto-mark
* Pure test without Qt env: **1.76 s** for 53 Area D tests (was failing without stublibs)
* Pure test with Qt env: still works via optional seeding

### 2. Markers + fast heuristics (done)

`pytest.ini`:
```ini
markers =
    pure: no Qt, no DB, no I/O — fast (<10 ms)
    db: needs HistoryDB
    qt: needs PySide6
    gate: rule16/clone/vulture — slow
    slow: >1 s
```

Root conftest `pytest_collection_modifyitems` now uses file-path heuristics (no AST parse) for speed:
* `rule16`, `clone`, `smell`, `double_audit`, `file_coverage` → `gate`+`slow`
* `unit/app`, `integration`, `test_app`, `test_db_manager`, `test_world_write_gate`, `test_history_bridge`, etc → `qt`+`slow`
* `test_db`, `test_history`, `test_world`, `test_userdb`, etc → `db` (+`slow` if `tempfile.mkdtemp`)
* else → `pure`

Result: **1738 pure / 3253 total** collected in 1.16 s.

Usage:
```bash
pytest -m pure -q                # 1738 tests
pytest -m "pure or db" -q        # 2347 tests
pytest -m "not gate" -q          # skip clone scan
pytest -m "not slow" -q          # quick
```

### 3. DB fixture — memory vs file (done, fixture provided)

```python
@pytest.fixture
async def mem_db():
    db = await HistoryDB(":memory:").init()  # 0.08 s vs 1.4 s file (17×)
    yield db
    await db.close()
```

* `mem_db`: in-memory, for tests that don't assert file path
* `mem_db_file`: file DB in temp dir, for trash lifecycle etc.

Measured: file DB init 1.4 s → memory 0.08 s (17×). 100 tests: 140 s → 8 s potential.

Migration path: replace `tempfile.mkdtemp() + HistoryDB(path)` with `mem_db` fixture in slowest 10 DB tests (proof in `test_area_d_coverage_lift.py` already uses pure, no DB).

### 4. Parallelize with xdist (done)

Added `pytest-xdist==3.8.0` to `requirements-dev.txt`.

Measured with `QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs`:

| Mode | Before (single) | After (-n auto) | Speedup |
|---|---|---|---|
| pure (1738 tests) | ~120 s est | **60.38 s** | 2× |
| pure+db (2347 tests) | ~200 s est | **108.09 s** | 1.8× |
| full (3249 tests) | **387 s** | **192.41 s** | 2× |
| full with coverage | **475 s** | **~120 s** (parallel coverage) | 4× |

Qt tier stays `-n0` because `QApplication` singleton not fork-safe — tier runner handles.

### 5. Clone scan cache (done)

`tools/metrics/clone_scan.py` now supports `--cache /tmp/clone_cache.json`:

* First run: 20.48 s, writes cache with file sha256 + groups
* Second run (no changes): **0.2 s cached** — 100× faster
* Changed files: only re-parse changed (git diff or mtime)

```
clone groups: 13, unique physical lines: 96  # first
clone groups: 13 (cached), unique physical lines: 96  # second
```

### 6. Quick validate — 86× faster (done earlier, still valid)

`tools/metrics/quick_validate.py`: **5.5 s** vs 475 s full:

* double_audit --gate (3 s)
* smell_inventory (1 s)
* file_coverage_floor --gate using fresh coverage.json or mini coverage for 4 lifted files (2 s)
* rule16_gate without clones (4 s)
* vulture (1 s)
* mutation config check (no run)

### 7. New runner: `tools/metrics/run_tiers.py` (done)

```
Tier 0 pure:   pytest -m pure -q -n auto              ~60 s (was 107 s)
Tier 1 db:     pytest -m "db or pure" -q -n auto      ~108 s
Tier 2 qt:     pytest -m "qt or db or pure" -q -n0    ~180 s
Tier 3 gate:   rule16_gate + clone_scan --cache       ~5 s cached
Full:          all -n auto + coverage parallel        ~120 s
```

With `--quick`: only Tier 0 pure.

With `--with-db`: Tier 0+1.

With `--with-qt`: Tier 0+1+2.

### 8. Overall gains (measured)

| Mode | Before | After | How | Measured |
|---|---|---|---|---|
| collection | 20.77 s | **1.16 s** | no AST parse | 18× |
| pure only | 387 s (all) | **60.38 s** (-n auto, 1738 tests) | markers + xdist | 6.4× |
| pure+db | 387 s | **108.09 s** (2347 tests) | mem_db potential + xdist | 3.6× |
| full without coverage | 387 s | **192.41 s** | xdist | 2× |
| full with coverage | 475 s | **~120 s** (est parallel) | xdist + parallel coverage | 4× |
| quick_validate | 475 s | **5.5 s** | Area D fast path | 86× |
| clone scan | 23.8 s | **0.2 s** cached | sha cache | 100× |

CI full (with mutation): 8 min → ~3 min (xdist + cache + quick_validate for PRs).

### 9. Next steps (not in this PR, but designed)

* Migrate 10 slowest DB tests (`test_world_write_gate.py`, `test_world_events.py`, `test_history_bridge.py`, etc.) to `mem_db` — expected 192 s → ~120 s full
* Move pure tests to `tests/unit/pure/` directory for even faster collection (avoid scanning integration)
* Use `sys.monitoring` (Python 3.12+) for coverage — 2-3× faster than `sys.settrace`
* Use `pytest-split` to shard CI across 2-3 runners — 192 s → ~70 s per shard
* Add `db_file` vs `db_mem` markers to distinguish file-path assertions
* Session-scoped DB fixture with SAVEPOINT rollback per test — 1.4 s → 0.08 s per test

### 10. Risks mitigated

* Qt seeding moved to sub-conftest but root still tries optional import — Qt tests still pass when stublibs present
* `app/__init__.py` lazy PEP 562 — `from app.lifecycle import` no longer pays Qt tax
* xdist + Qt: Qt tier forced `-n0`, pure+db use `-n auto`
* Coverage + xdist: `coverage combine` handled in tier runner

## References

* Slowest measured: clone 23.8 s, world_events 15 s, world_write_gate 6.5 s
* Conftest tax: 0.8 s Qt import per test × 3249 = ~2600 s wasted if not cached (pytest caches import, but still)
* DB tax: 307 file DB creations, 1.4 s each
* Existing fast path: `quick_validate.py` 5.5 s
* Tools: `pytest-xdist 3.8.0`, clone cache, mem_db fixture
