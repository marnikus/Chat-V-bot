# Round K — the test suite's wall clock (design, 2026-09-15)

> **Status: plan, not yet implemented.** Written after a measured investigation
> of where the suite's 6½ minutes go. The numbers below are reproducible with
> `tools/metrics/wait_budget.py`, which ships with this plan (inert unless
> loaded: `-p tools.metrics.wait_budget`).
>
> **Scope:** the *time* the suite costs, not the code it proves. No test's
> assertions are in scope for weakening, no test is in scope for deletion, and
> no production behaviour changes except where a wait is implemented as a fixed
> sleep and the wait itself is what a test is paying for.
>
> **Prompted by:** the Round J closing battery — 8½ minutes of coverage run per
> iteration, and a full-suite re-run for every intermediate question. This is
> the measurement of that cost and the architecture that removes it.

---

## 1. The measurement

Frozen tree at `29b19df` (Round J's closing commit), sandbox = 2 vCPU, offscreen
Qt, the real-WebEngine sash test deselected:

```bash
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m pytest tests -q -p no:cacheprovider --durations=0 \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine

PYTHONPATH=. .venv/bin/python -m pytest tests -q -p no:cacheprovider \
  -p tools.metrics.wait_budget --deselect=…::test_grid_in_real_webengine
```

| quantity | value |
|---|---:|
| wall clock | **386.5 s** (6 m 26 s) |
| test CPU (`user` 130.7 s + `sys` 23.7 s) | **154 s** → 40 % of one core, 20 % of the box |
| result | 3283 passed, 2 skipped, 1 xfailed, 1 deselected, 934 subtests |
| collection (all 3287 imports) | **2.0 s** |
| `setup` phase, entire suite | **0.2 s** |
| `asyncio.sleep` requested | **251.75 s** over 3544 calls |
| `time.sleep` requested | 0.0 s (1 call) |
| subprocess spawns | 70, costing **23.0 s** — `tests/test_rule16_new_code.py` alone: 12 spawns, **21.2 s** (it shells out to the gate, which shells out to radon / pylint / vulture) |
| SQLite connects | 1572 (1506 through `aiosqlite`) |

Instrument overhead is negligible: the same full run with the probe loaded took
378.5 s against the 386.5 s baseline. Spawn counts are one per logical spawn —
the probe's first revision double-counted `subprocess.run`'s internal `Popen`
(138 spawns / 24.4 s); the number above is the fixed instrument's, and the
tool's own tests pin that guard.

**The suite is not CPU-bound. It is waiting.** 252 s of a 386 s run is literally
`await asyncio.sleep(...)` in code the tests exercise; a cProfile of
`tests/test_world_write_gate.py` puts **77 % of that file's time in
`select.epoll.poll`** — the event loop idling on timers.

### 1.1 Who requests the waiting

| requested | calls | mean | caller |
|---:|---:|---:|---|
| 117.3 s | 391 | 300 ms | `backend/chat_parser_settle.py` (`SettleSpec.wait_ms` default) |
| 24.5 s | 1123 | 22 ms | `tests/test_world_write_gate.py` (`settle(times=40, step=0.02)` = 0.8 s/call) |
| 15.5 s | 317 | 49 ms | `services/world_events.py` |
| 15.1 s | 32 | 472 ms | `actions/base.py` |
| 15.0 s | 3 | 5000 ms | `tests/integration/run_safety/_helpers.py` |
| 12.1 s | 172 | 70 ms | `backend/scroll_parser_dom.py` |
| 11.3 s | 38 | 296 ms | `backend/visual_click.py` |
| 10.8 s | 6 | 1792 ms | `tests/integration/run_safety/test_cleanup_contract.py` |
| 4.7 s | 162 | 29 ms | `actions/cancellation.py` |
| 3.6 s | 345 | 11 ms | `tests/test_db_manager.py` |
| 3.5 s | 7 | 500 ms | `app/lifecycle.py` |
| 6.5 s | 23 | 200–360 ms | `services/run/queue_select.py`, `stores/world_lock.py`, `backend/chat_sync_read.py`, `backend/scroll_parser_judge.py`, `backend/message_injector*.py` |
| 0.7 s | 17 | 38 ms | node harness (`tests/js_harness.js` probes) — the three largest users measured; the harness is *cheap*, so batching it is not worth a step |

The ten worst **tests** by wait budget (per-test attribution, `WAIT_REPORT`):

| wait | test |
|---:|---|
| 14.85 s | `tests/unit/services/test_world_events.py::TestRunWhenWorldOpen::test_a_world_that_never_opens_still_reports_itself` |
| 6.20 s | `tests/test_world_write_gate.py::TestTrashLifecycle::test_a_dropped_step_cannot_be_undone_into_a_success` |
| 5.80 s | `tests/test_world_write_gate.py::TestUndoProvesItself::test_a_refused_undo_reports_and_stays_retryable` |
| 5.30 s + 3×5.15 s | `tests/integration/run_safety/test_cleanup_contract.py` + `test_cycle_event_order.py` |
| 4.20 s | `tests/test_chat_parser_delta.py::TestSyncScenarios::test_scroll_that_empties_the_pane_is_retried_not_marked_done` |
| 3.00 s ×2 | `tests/test_world_write_gate.py::TestUndoProvesItself` (`clear_history`, `redo`) |
| 2.20 s ×2 | `tests/test_world_write_gate.py::TestUndoProvesItself` (`delete_then_undo`, `db_window_told`) |

### 1.2 The tiers, measured

| tier | tests | wall clock | wait budget | `-n 2 --dist worksteal` |
|---|---:|---:|---:|---:|
| `tests/` (root files) | 1524 | **274.8 s** | ~160 s | — |
| `tests/unit/` | 1156 | **57.4 s** | **45.7 s** | **30.6 s** (1.88×) |
| `tests/integration/` | 603 | **45.6 s** | **45.7 s** | — |
| whole suite | 3283 | **386.5 s** | **251.8 s** | **200.1 s** (1.93×) |

The tier wall clocks sum to 378 s of the 386.5 s total (the rest is session
setup), so the split is exact rather than apportioned.

Two structural facts fall out of `setup = 0.2 s` and `collection = 2.0 s`:

* **There is no fixture overhead to remove.** All 3287 tests declare no scoped
  fixtures at all — every expensive object is built inside the test body, which
  is why the `setup` phase measures 0.2 s. The standard advice ("scope your
  fixtures up") buys *nothing* here, and this design does not chase it.
* **Imports are not the problem either** — 2.0 s to collect and import the whole
  tree. The per-worker cost of `-n` is therefore small.

### 1.3 Coverage is the verify-loop tax

| run | without coverage | with `--cov-branch` | overhead |
|---|---:|---:|---:|
| `tests/unit` (1156 tests) | 57.5 s | 69.3 s | **+20.6 %** |
| whole suite (Round J's own runs) | 386.5 s | 498.7 s | **+29 %** |

(Note for later: `COVERAGE_CORE=sysmon`, coverage.py's low-overhead core, needs
Python ≥ 3.12 for branch measurement. The sandbox runs 3.11.2, so it is not
available to this round; if the project moves to 3.12+, re-measure — it is the
cheapest single change on that axis.)

### 1.4 Three counter-experiments — two of them rejected

Both were run over the whole suite, unchanged tests, same box:

| experiment | wall clock | result | verdict |
|---|---:|---|---|
| **`-n 2 --dist worksteal`** (pytest-xdist 3.8.0) | **200.1 s** | **3283 passed**, identical skips/xfails | **adopt** — 1.93×, zero test changes |
| **sleep cap**: every `asyncio.sleep(d)` truncated to 1 ms | 210.5 s | **9 failed**, and the poll loops then iterate 5.5× more (19 597 calls, 1654 s requested) | rejected |
| **virtual clock**: `sleep(d)` returns after one iteration, logical time advances by the full `d` | 196.0 s | **43 failed**, 887 500 sleeps (instant polls spin at CPU speed) | rejected |

The rejected pair is this design's most useful result: **the wait cannot be
bought back by lying to the clock.** Truncating a delay changes timing
semantics; making time advance instantly turns every poll into a busy loop and
exposes races that production spacing was hiding. The waits have to become
*shorter because the thing being waited for is signalled*, or because the
spacing is a parameter the test is allowed to shorten — never because the clock
lies.

---

## 2. The redesign

Five layers, in the order they pay.

### L1 — waits become signalled, or spaced by a parameter the test owns (≈200 s of the 252 s)

Three shapes exist in the tree, and each has a mechanical replacement.

1. **Poll-until-stable at production spacing.** `chat_parser_settle.settle_after_top`
   (117.3 s), `scroll_parser_dom` (12.1 s), `visual_click` (11.3 s),
   `scroll_parser_judge` (1.5 s) poll an external (the DOM, a CDP page) until it
   stops changing. The spacing is already a parameter — `SettleSpec.wait_ms = 300`
   — and tests simply never shorten it. **Fix:** a shared `FAST_SETTLE` spec
   (5 ms spacing, short deadline) that every test driving the path passes. The
   loop still polls to stability, `stable_polls` and `max_wait_s` still bind,
   the timeout path still reports `_settled=False`; only the spacing changes.
2. **"Let the scheduled tasks finish" budgets.** `settle(times=40, step=0.02)`
   in `tests/test_world_write_gate.py` (24.5 s over 1123 calls),
   `run_safety/_helpers.py`'s 3 × 5 s, `test_cleanup_contract.py`'s 6 × 1.8 s,
   `tests/test_db_manager.py`'s 345 small sleeps. These wait for work the
   product *already hands back* — a task, a queue, an event. **Fix:** `await` the
   task or the event. The suite already contains this idiom
   (`gate.wait()`, `wrote.wait()`, `commit.wait()`, `hold.wait()`), so the
   pattern is established; the round generalises it and bans the new fixed
   budgets. This also removes nondeterminism: "wait 0.8 s and hope" is exactly
   what Round I's sleep ratchet was written to stop.
3. **Production loops whose sleep is really a deadline wait.**
   `services/world_events.py` (15.5 s), `actions/base.py` (15.1 s),
   `actions/cancellation.py` (4.7 s), `app/lifecycle.py` (3.5 s),
   `services/run/queue_select.py` (2.2 s), `stores/world_lock.py` (1.8 s),
   `chat_sync_read.py` (1.6 s), `message_injector*.py` (1.8 s). Each mixes a
   deadline (`time.monotonic()` **or** `asyncio.get_event_loop().time()` — both
   forms are in the tree, note the seam must cover both) with a fixed spacing.
   **Fix:** one seam, `core/clock.py`, exposing `now()` and `pause(seconds)`,
   adopted by these modules with their production defaults unchanged; the test
   suite installs a **fast clock** for the session (real 1–5 ms spacing, virtual
   deadline accounting) so the loops converge in the same number of iterations
   at CPU speed. Where a test asserts elapsed *real* time, it keeps the real
   clock (`realtime` marker).

### L2 — the gate tier leaves the default run (38.8 s, and 21.2 s of subprocess)

`tests/test_rule16_new_code.py` is the slowest file in the tree: 13 tests,
38.8 s, and it shells out to `tools/metrics/rule16_gate.py` **12 times** inside
the suite. The same gate is a pre-commit hook (`tools/ci/quality-gate.yml`,
`.pre-commit-config.yaml`). It becomes its own tier:

```bash
.venv/bin/python -m pytest -m gate          # the hook/CI runs this when it matters
.venv/bin/python -m pytest -m "not gate"    # everything else
```

Nothing goes unenforced: the hook runs the gate before the commit lands, the CI
job runs the gate tier, and the round's closing battery runs it too.

### L3 — parallelism, measured rather than assumed (386 s → 200 s, today)

`pytest-xdist` 3.8.0, pinned in `requirements-dev.txt`, with
`--dist worksteal` (the default `load` scheduler balances badly when durations
vary by 100×). Measured today at 1.93× on 2 vCPU with **zero test changes**, and
the suite is only 20 % CPU-busy, so the same command on a 4–8 vCPU developer
machine has room for 3–4×. Per-worker collection is ~2 s.

### L4 — the edit loop stops paying for the verify loop

* **Re-enable pytest's cache.** `pytest.ini`'s `addopts = -p no:cacheprovider`
  disables `--lf`, `--ff` and the duration cache for every user, everywhere.
  Removing it needs one line in `.gitignore` (`.pytest_cache/`), which is
  currently *not* ignored — a detail this plan exists to catch rather than
  discover by accident.
* **Tier the commands** (§3): an edit runs seconds of tests, a commit runs the
  full battery, the verify job runs the gate tier plus exactly **one**
  coverage run (the instrument costs +29 %, and Round J measured eight 8-minute
  runs in one round).
* **Keep the wall-clock number in the docs** the same way Round J kept coverage:
  suite wall clock, wait budget and per-tier numbers in the round's battery.

### L5 — the ratchet changes units

Round I's ratchet counts *sites*: 64 literal short `asyncio.sleep(0.0N)` calls,
per file. That counts the symptom. The new instrument counts the **requested
wait budget in seconds, per file**, from a run of the suite
(`tools/metrics/wait_budget.py`), so:

* a single new 2 s budget fails even though it is one call;
* the number can only go down, file by file — the same shape as the sleep
  ratchet, in the unit that actually costs the developer time.

Both instruments stay: the static one catches a new `sleep(0.05)` at review
time, the measured one catches a wall-clock regression at verify time.

---

## 3. The command matrix this design ships

| loop | command | today | target |
|---|---|---|---|
| edit → red/green | `pytest -q tests/unit -m "not gate"` | 57.4 s | **< 20 s** |
| same, 2 workers | `… -n 2 --dist worksteal` | 30.6 s | **< 12 s** |
| before commit | `pytest -q -m "not gate" -n 2 --dist worksteal` | ~350 s | **< 90 s** |
| verify job | full suite `-n 2 --dist worksteal` | 386.5 s | **< 180 s** |
| verify job, coverage | the same run with `--cov-branch --cov=…` | 498.7 s | **< 250 s** |
| gate tier | `pytest -m gate` (hook + CI) | 38.8 s | ~25 s |
| nobody | bare `pytest` at production spacing, to answer "is it fast yet" | 386.5 s | — |

---

## 4. Steps

One commit per step; each step names what it owns and the number that closes it.
The acceptance numbers are measured on the *same* box and tree as §1, and every
step must leave RULE 16's gate green (`--with-clones`), the API snapshot
additive, and the sleep ratchet at 64/64 or lower.

| step | what | owns | closed by |
|---|---|---|---|
| **K-1** | the instrument, committed and reproducible; a baseline JSON (`tools/metrics/wait_baseline.json`) and a `--compare` mode so the ceiling table is enforceable | `tools/metrics/wait_budget.py` | the probe re-measures §1 within ±5 %; `--compare` fails on a raised ceiling |
| **K-2** | `core/clock.py` — `now()`, `pause(seconds)`, install/reset — adopted by the eleven production wait owners of §1.1(3) with production defaults unchanged | `core/clock.py` + `services/world_events.py`, `actions/base.py`, `actions/cancellation.py`, `app/lifecycle.py`, `services/run/queue_select.py`, `stores/world_lock.py`, `backend/chat_sync_read.py`, `backend/message_injector*.py` | suite green at production spacing; every new function inside RULE 16's limits; no public symbol moves |
| **K-3** | the test-side fast clock: session-scoped install + `realtime` marker, and the tests the PoC showed need wall clock marked with it | `tests/conftest.py`, the ~9 tests measured in §1.4 | full suite green with the fast clock on, the `realtime` subset green in the same run |
| **K-4** | `FAST_SETTLE` and its callers — the 117 s | `tests/unit/backend/test_chat_sync_phases.py`, `tests/test_chat_parser_delta.py`, `tests/test_private_gate.py`, `tests/test_media_recovery_e2e.py`, `tests/integration/services/test_services_collector_gaps.py`, `tests/integration/services/test_collector_tick_phases.py` | `chat_parser_settle` wait ≤ 5 s; the settle/retry/timeout assertions unchanged |
| **K-5** | signalled waits replace fixed budgets | `tests/test_world_write_gate.py` (24.5 s), `tests/integration/run_safety/_helpers.py` (15 s), `run_safety/test_cleanup_contract.py` + `test_cycle_event_order.py` (16 s), `tests/test_db_manager.py` (3.6 s), `tests/unit/services/test_world_events.py` (14.9 s) | each file's wait budget ≤ 1 s; identical assertions |
| **K-6** | tiers and markers (`gate`, `slow`), registered in `pytest.ini`, with the command matrix in the docs | `pytest.ini`, ~16 files, `docs/current/AGENT_RULES.md` | `-m "not gate"` deselects exactly one file; `pytest -q tests/unit` < 20 s |
| **K-7** | parallelism adopted: pin `pytest-xdist`, document `-n auto --dist worksteal`, wire the CI job | `requirements-dev.txt`, `tools/ci/quality-gate.yml`, `README.md` | full suite `-n 2` < 110 s, green twice in a row (flake check) |
| **K-8** | the closing battery: before/after table, one coverage run, ratchet JSON in band, sleep ratchet unchanged, docs + SOR updated | `docs/archive/2026-09-15-round-k-test-time/`, `docs/README.md`, `docs/archive/README.md`, `docs/current/SYSTEM_OF_RECORD.md` | the as-built half carries the measured numbers |

K-2 and K-3 are separable, and *must* be: the production seam lands with
production defaults, the test-side fast clock lands behind its own commit, so a
regression in either is attributable to one of them.

## 5. What this round does not do

* **No assertion moves.** Not one `assert` changes shape: the redesign changes
  *when* a test looks, never *what* it looks at.
* **No test is deleted or weakened.** The gate tests change tier, not content;
  the `realtime` marker *adds* fidelity (those tests keep the real clock on
  purpose).
* **No global time monkeypatching.** §1.4 measured the two ways that goes wrong
  (9 and 43 failures). The clock seam is per-module and its fast implementation
  is installed by the test session only.
* **No fixture re-scoping, no import surgery.** §1.2 measured both as non-issues
  (`setup` 0.2 s, collection 2.0 s).
* **No coverage-threshold change, no new test framework.** The suite stays
  `unittest`-style under pytest; only the runner flags change.
* **Nothing from Areas A/D**, and no Round J file is re-opened.

## 6. Risks

| risk | mitigation |
|---|---|
| the fast clock hides a genuine timing dependency | it is installed session-wide but the `realtime` marker is one line to opt out, and the PoC already names the 9 tests that need it; K-3 requires the full suite green in *both* modes |
| a "signalled wait" silently changes what a test waits for | each replacement is one test file at a time (K-4/K-5), with the assertion set unchanged, and the wait budget table re-measured per step |
| parallelism surfaces hidden shared state | measured: `-n 2` is already green at baseline. Before K-7 closes, the run must be green twice, and any flake found is fixed rather than retried away |
| moving the gate tier out of the default run weakens the gate | the pre-commit hook already runs it, CI runs the tier, and the closing battery quotes its output; the tier is a *placement* change, not a deletion |
| the design becomes a second thing to maintain | the instrument is one file and the ratchet is a ceiling table read by that file; both are already in the round's own doc |

## 7. Expected result

Arithmetic from §1, before measuring K-8:

| | today | after L1 (serial) | after L1+L3 (`-n 2`) |
|---|---:|---:|---:|
| whole suite | 386.5 s | **~170 s** | **~95 s** |
| `tests/unit` ("is my edit green?") | 57.4 s | ~17 s | ~10 s |
| wait budget | 251.8 s | **≤ 60 s** | — |
| coverage run | 498.7 s | ~230 s | ~130 s |

The round's real acceptance is not the estimate table: it is that **the numbers
are re-measured, per step, and the as-built half of this document replaces the
"after" column with what actually happened** — the same discipline Round J used
for its criteria table.
