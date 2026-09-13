# Round 4 — steps 4 and 5 completed (2026-09-12)

**Completed:** persistence/live-result extraction, read/alignment extraction,
and a separately tested correction to cooperative stop during retry/pacing.
**Next:** step 6 (session lifecycle), then step 7 (final compatibility facade).
Steps 8–9 remain queued. The remaining session class is not claimed to fit the
new-code size limits.

Design: `docs/archive/2026-09-12-refactor-round4/STEPS_4_5_DESIGN.md`.
Master queue: `docs/archive/2026-09-12-refactor-round4/ROUND4_DESIGN.md`.
Previous slice: `reports/REFACTOR_ROUND4_2026-09-12.md`.
Work remains on `arena/01a093f4-chat-v-bot`.

## 1. Implemented boundaries

| Owner | Responsibility | Physical lines |
|---|---|---:|
| `backend/sync/planning.py` | Immutable options and pure read decisions, unchanged this slice | 221 |
| `backend/sync/persistence.py` | `SyncPersister`, cursor/gap/media writes and bounded live-result aggregation | 173 |
| `backend/sync/reading.py` | `ChunkReader`, retry/pacing, `DeltaAligner` | 149 |
| `backend/chat_sync.py` | Session lifecycle, orchestration and legacy exports | **600 → 337** |

The original facade names resolve to the same extracted objects. Existing
API snapshots are unchanged. Fresh-process import tests prove neither new
phase imports the session/facade, parser, services, Qt or action registry at
module load. Cancellation helpers are imported lazily when a cooperative wait
is actually needed, avoiding the action registry's auto-scan import cycle.

### Step 4 — persistence

Preserved the exact production function/class bodies (comments excluded):

* incomplete cursors retain the head but clear tail signatures;
* cap gaps use the archive's last ordinal and are recorded before chunk writes;
* prepended/old/invalid-ordinal rows do not enter the live-update channel;
* live results remain capped across multiple chunks;
* media repair failures are contained/logged, while external cancellation and
  ordinary append failures still propagate;
* streamed writes and aligned batch/prepend order are unchanged.

A new real-SQLite test proves partial sync → retry → unchanged fast path
preserves exactly four archived messages without duplicating the first chunk.

### Step 5A — read/alignment extraction

Moved both classes and `SLICE_RETRIES`, preserving behavior first. AST comparison
against a saved pre-step working-tree source matched **every retained and moved
class/function definition**. The focused original/characterization suites passed
before and after the move: **83 passed, six subtests**.

The alignment prefix includes the matched stored tail; repository deduplication
handles known rows. No alignment algorithm or snapshot was changed.

### Step 5B — explicit stop correction, not an invisible file-move change

Five new regression cases failed against the extracted-but-unchanged reader:
stop on the first/last empty retry, stop during retry delay/pacing, and stop as
the final nonempty slice completed. An external-cancellation test already passed.
All six pass after the fix.

`_stopping()` now latches the stopped outcome, and retry boundaries check it.
`_pause()` uses the existing 20ms cooperative sleep slices when a callable stop
predicate is configured, catching **only `RunStopped`**. Without one, the
original single sleep/duration remains unchanged. No duplicate stop timer,
background task, new timeout policy or broad cancellation catch was introduced.

Contracts preserved/clarified:

* Empty retries without a stop remain `no_new`; stopped retries report `stopped`.
* A completed nonempty chunk is retained, including write/progress/position,
  even when stop arrives during that slice. The final cursor still records the
  partial boundary without advertising a complete tail.
* External `CancelledError` propagates from page reads, retry/pacing waits,
  repository writes and media recovery; cancellation does not forge a final
  success cursor.
* Cooperative stop does **not** cancel an already-issued CDP slice or viewport
  request. It takes effect at that await boundary; supervising those operations
  would require a separate lifecycle/transaction decision. No claim of bounded
  latency for those in-flight requests is made here.

## 2. RULE 16 / RULE 18 final review

New phase scopes are automatically enumerated by
`tests/test_sync_phase_quality.py`, using the existing RULE 16 measurement
engine. Missing CC/cognitive tools fail the new checks rather than silently
skipping measurement. Existing stage-1–3 checks remain intact.

| Scope | Max function LOC | Max params | Max CC | Max cognitive | Max nesting |
|---|---:|---:|---:|---:|---:|
| Persistence | 28 | 3 | 9 | 9 | 2 |
| Reading/alignment | 21 | 3 | 9 | 10 | 2 |

| Extracted class | LOC | Direct methods | Review |
|---|---:|---:|---|
| `SyncPersister` | 135 | 12 | Below hard 150/15 limits; ideal deviation documented for the frozen single-policy write interface |
| `ChunkReader` | 98 | 8 | Within the 120/10 preferences despite adding stop handling |
| `DeltaAligner` | 31 | 2 | Small cohesive alignment owner |

No new hard-limit overrides. `repair_tail` (28 lines) and `read` (21) have
explicit ideal-size reasons for their exception/ordered-chunk boundaries.
The 149-line reading file is a cohesive leaf, not padded to reach 150.
The package now has four cohesive files; the remaining lifecycle work will
bring it toward the planned 5–7. Runtime is still 337 lines and its unchanged
`SyncSession` is still 248 lines / 24 methods: this is the explicit step-6 debt.

RULE 19: no nesting/CC breach required simplification before extraction. The
stop correction adds real decisions, all within hard limits; no metric was
hidden in a lambda, cosmetic class split or unrelated re-export.

## 3. Validation results

| Check | Result |
|---|---|
| Full Python suite | **2752 passed**, 3 skipped, 1 deselected, 1 xfailed; 774 subtests |
| Added tests this slice | **55**, including 24 scoped phase quality checks |
| Standalone RULE 16 suite | **23 passed**, measuring tools installed |
| Node harnesses | **25 files passed**, zero failures |
| Existing backend/stores API snapshots | pass; no golden files changed |
| Exact-AST clone gate | zero new groups, zero stale baseline entries |
| Vulture >= 90% | same seven pre-existing findings; no new findings |
| Pylint unused imports on sync production scope | zero findings |
| `git diff --check` | clean |

### Coverage, measured separately

| Metric | Previous slice | Steps 4–5 |
|---|---:|---:|
| Overall line | **91.04821%** (13446 / 14768) | **91.13710%** (13481 / 14792) |
| Overall branch | **85.77729%** (3112 / 3628) | **85.91084%** (3122 / 3634) |
| New persistence module | — | **100% lines**, **94.44% branches** |
| New reading module | — | **98.88% lines**, **97.22% branches** |

Every extracted/new production function is exercised under behavioral tests;
there are no zero-hit functions in either new phase. The two new stop helpers
are fully line-covered. Coverage improves over both the preceding slice and
the frozen RULE 16 floors. Combined coverage.py percentage is not used as a gate.

### Honest exceptions / remaining limits

* One existing test's import-count bookkeeping changed **38 → 39**, following
  its documented bump rule: session and persistence now each directly import
  store value types. No store interface or behavioral assertion was weakened.
  Rerouting imports merely to conceal the count was rejected.
* Real WebEngine rendering remains deselected on this headless machine. Qt
  imports use repository-built `/tmp/stublibs`; this is not a Chrome UI smoke test.
* The pre-existing unawaited collector-push coroutine warning remains (one warning).
* Mutation is configured only for untouched `backend/history_query.py`; no
  mutation score is claimed for these phases. The general changed-code gate
  and CI activation are still step-8 work, not solved by scoped tests.

## 4. Reproduce

Install `requirements-dev.txt` in `.venv`; build Qt stubs if needed using
`.venv/bin/python tools/build_stubs.py .venv /tmp/stublibs`.
Keep generated logs/audits/coverage outside Git.

```bash
.venv/bin/radon cc -s backend/sync/persistence.py backend/sync/reading.py
.venv/bin/python tests/test_rule16_new_code.py
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
.venv/bin/python -m coverage json -o /home/user/round4-step45-coverage.json
.venv/bin/python tools/metrics/current_audit.py > /home/user/round4-step45-audit.json
for f in tests/test_*.js; do node "$f" || exit 1; done
```
