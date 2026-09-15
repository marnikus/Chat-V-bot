# Test battery — tiers, parallelism, and the 2026-09-15 speed redesign

The whole battery used to be one 6-minute `pytest tests/` command. Every
small change paid for the subprocess-heavy quality gates and the full
Node-under-V8-coverage run, and nothing could run while the 3 188 Python
tests queued up one after another.

## The tiers

`tests/run_batteries.sh` (the only thing to remember):

| Tier | What runs | Wall time here (2 cores) |
|---|---|---|
| `fast` | `tests/unit`, parallel | ~25 s |
| `js` | the 41 Node suites, parallel | ~5 s |
| `medium` | every Python test **except** the two gate files, parallel | ~2 min |
| `gates` | `test_js_gate.py` + `test_rule16_new_code.py`, serial | ~26 s |
| `full` | `js` + `medium` + `gates` — what a commit must pass | **~3 min 25 s** (was 6 min 28 s) |

`tests/test_sash_webengine.py` (real `QWebEngine`) is excluded from every
tier and runs on demand — it is the one suite that needs a GPU-ish
environment and a display.

**`fast` for iterating, `full` before committing.** Nothing else has to be
typed: `tests/run_batteries.sh` (no args) is `full`.

## Why the suites are safe to parallelise

Parallelism is only safe because the isolation is already real. Verified
before `-n auto` was wired in:

* 107 test files build their state with `tempfile.mkdtemp` /
  `TemporaryDirectory` — per-test directories, never shared paths.
* No test binds a socket or a port (the CDP side is faked).
* No test mutates `os.environ` or writes a fixed path under the repo.
* Each pytest-xdist worker is a separate process: its own real PySide6,
  its own conftest seeding, its own per-test Qt-fake teardown gate.
* The Node suites already owned their globals in separate processes —
  they just started with `xargs -P` instead of one at a time.

If a future test breaks that contract (a fixed path, a shared port, an
env leak), the battery will flake in parallel first and serial second —
fix the isolation, do not turn parallelism off.

## What the profile found (where the 6 minutes actually went)

`pytest --durations=60` on the 2026-09-15 baseline:

| Hot spot | Was | Fix |
|---|---:|---|
| `test_rule16_new_code.py` — **7** tests, each re-running vulture + pylint + the AST measurements | ~44 s | mtime-keyed caches in `tools/metrics/rule16_gate.py` (`_AST_CACHE`, `_CC_CACHE`, `_SMELL_CACHE`, `_CLONE_CACHE`); a write invalidates, a stale read is impossible. The ~20 s clone scan now happens once per session, not four times |
| `test_world_events.py::test_a_world_that_never_opens…` | 15 s | the production helper `wait_for_world_open` already reads `WAIT_S` **at call time so a test can shorten it** — the test finally does. 15 s → 0.2 s |
| `test_js_gate.py` — Node suites under V8 coverage, one at a time, on a 116 MB mirror of the whole repo | ~12 s | the mirror is now just `ui/ + bridge/ + backend/js/ + tests/` (a few MB — that is all the Node suites ever read), and the suites run in a `ProcessPoolExecutor` (V8 writes PID-unique coverage filenames, so the shared dir is safe). 12 s → 7 s, identical numbers |
| everything else (3 188 tests × real DBs, real Qt classes, asyncio loops) | ~300 s | pytest-xdist `-n auto` |

The remaining serial costs are the ones worth keeping serial: the gate
files spawn their own subprocess scanners (doubling the work per worker
would make them *slower*), and the clone scan genuinely reads the whole
production tree.

## Files

* `tests/run_batteries.sh` — the tiered runner (bash, no new deps beyond
  `pytest-xdist`, which is in `requirements-dev.txt`).
* `tools/metrics/rule16_gate.py` — mtime-keyed scan caches (behaviour
  unchanged: a fresh process, e.g. the pre-commit hook, sees an empty
  cache; a modified file invalidates its entry).
* `tools/metrics/js_coverage.py` — subset mirror + parallel Node runs
  (measurement semantics unchanged: same suites, same union of covered
  lines — the re-baselined reports still verify byte-identical totals).
* `tests/unit/services/test_world_events.py` — the 15 s timeout test now
  shortens `WAIT_S` for the give-up path it is pinning.

## Reproduce the numbers

```bash
tests/run_batteries.sh full     # ≈ 3 min 25 s on a 2-core box
tests/run_batteries.sh fast     # ≈ 25 s
```

The baseline (pre-redesign, same box): `pytest tests/ -q
--ignore=tests/test_sash_webengine.py` → 388 s serial.
