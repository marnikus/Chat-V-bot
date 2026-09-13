# Round 4, steps 4–5 — persistence and read/alignment boundaries

Design written 2026-09-12, continuing the working tree from stages 1–3.
See `docs/archive/2026-09-12-refactor-round4/ROUND4_DESIGN.md` for the queue.
The preceding slice's full-suite baseline is 2697 passed, 3 skipped,
1 deselected, 1 xfailed; line 91.04821%, branch 85.77729%.

## Scope and research

`backend/chat_sync.py` is now 600 lines. Current measurements:

| Unit | LOC | CC | cognitive | nesting | methods |
|---|---:|---:|---:|---:|---:|
| `merge_live` | 18 | 7 | 9 | 2 | — |
| `SyncPersister` | 133 | — | — | — | 12 |
| `repair_tail` | 28 | 9 | 8 | 2 | — |
| `ChunkReader` | 72 | — | — | — | 6 |
| `read` | 21 | 5 | 7 | 2 | — |
| `_window` | 13 | 4 | 6 | 2 | — |
| `DeltaAligner` | 31 | — | — | — | 2 |
| `split` | 15 | 9 | 6 | 1 | — |
| residual `SyncSession` | 248 | — | — | — | 24 |

Existing tests already pin streaming vs buffered reads, cap-gap-before-write,
empty cursors, private gate refusal, viewport restoration and media recovery.
Additional characterization must cover cancellation at read/write boundaries,
partial-cursor tail clearing, bounded live results, and failed tail repair.

## Step 4 — isolate the archive write policy

Move `merge_live` and `SyncPersister` verbatim to
`backend/sync/persistence.py`. Imports point to standard-library logging and
`stores.history_models` value types; no runtime import of the session/facade.
Keep `backend.chat_sync` re-exports as the same objects and preserve all method
signatures and result fields. Preserve record/gap/cursor order, prepend-vs-live
filtering, media failure logging, and propagation of `CancelledError`.

Target: file 150–200 lines, functions <= 30, class <= 150 / 15 methods.
The existing 133-line class exceeds the 120-line *ideal*, not the hard gate:
its 12 frozen entry points share one session/repository write policy. Annotate
this constraint; do not introduce trivial delegating classes to hide it.
`repair_tail` remains a 28-line single read/recover exception boundary, with
an ideal-size explanation. No new hard-limit overrides.

## Step 5A — isolate paced reading and alignment

Move `ChunkReader`, `DeltaAligner`, and `SLICE_RETRIES` to
`backend/sync/reading.py`; preserve the public facade names. It may import the
archive's `align_batch` helper but not the session, Qt or services. These two
classes form the streaming/buffered read policy, not separate micro-modules.

Check AST equality for every moved definition against the pre-step tree and
run the existing sync suites before changing behavior. Runtime should shrink
to approximately 350 lines. Leave the session and `run_sync` in place: moving
those is explicitly steps 6–7, not part of this request.

## Step 5B — separate, test-first stop correction

Research found a real gap: `_window` does not check stop between retries;
a stop while an empty range is retried can consume all four attempts and
finish as `no_new` instead of `stopped`. Configured pacing uses one uninterruptible
sleep. These are RULE 7 issues, not harmless consequences of moving a file.

Add failing tests first, then change only the read policy:

* `_stopping()` latches a cooperative stop on the result; check at each retry,
  after an empty slice, and after the read loop. Empty without stop remains
  `no_new`; exceptions remain exceptions.
* `_pause(delay)` uses the existing `sleep_with_stop` for a configured callable
  predicate and catches **only** `RunStopped`, latching the outcome. Without a
  callable predicate keep the existing single sleep (including its observable
  duration). Import cancellation helpers lazily because importing `actions`
  auto-scans the block registry and would cause a module-load cycle here.
* Preserve the established completed-chunk contract: a nonempty slice that
  finishes while stop is requested is accepted as one whole chunk, including
  its write/progress/position update. Do not cancel repository writes, discard
  a completed chunk, or suppress final partial-cursor bookkeeping.
* External `CancelledError` propagates through reads, waits, writes and media
  recovery. No additional tasks, timeout policy or synthetic error result.
* Already-issued CDP slice/viewport requests still complete at their existing
  await boundary on cooperative stop. Supervising those requests would alter
  the completed-chunk contract and belongs to the lifecycle design, not this
  narrowly bounded retry/pacing fix. External task cancellation still works.

This substep is explicitly a behavior fix, not covered by the AST-equivalence
claim of 5A. Target read class <= 120 lines / 10 methods; all functions CC <= 10,
cognitive <= 15, nesting <= 4, LOC <= 30, parameters <= 4.

## Verification and rejected shortcuts

Add executable boundary tests (fresh imports, real public sync calls, real
SQLite persistence where useful), and auto-discovered RULE 16 checks for both
new files. Keep old snapshots/tests intact. Run focused tests before and after
the move, then the full suite with branch coverage, standalone quality gate,
clone scan, Vulture, Pylint unused imports and all Node harnesses.

No regenerated API snapshot, changed `__module__`, conditional lambdas hiding
CC, duplicated stop timer implementation, broad cancellation catch, moved
session god class, or missing-tool skips in new quality checks. Coverage must
not fall below the previous slice. Mutation is not configured for these modules;
report that limitation rather than inventing a score.

Outcome report: `reports/REFACTOR_ROUND4_STEPS_4_5_2026-09-12.md`.
Update current doc/map by replacing older rows, not growing the already
oversized system-of-record context file. Steps 6–9 stay queued.

## Validation discoveries

* The unchanged characterization suite passed before/after extraction (83 tests,
  six subtests). AST comparison matched every moved and retained definition.
* Five new stop regressions failed before the separate 5B fix; the cancellation
  test already passed. All six pass after it.
* The stores import-count test reports 39 instead of 38 because the newly
  separated session and persistence owners each import store value types.
  Follow that test's explicit rule permitting a bump for legitimate imports:
  update only this count/comment, not the stores API or any golden snapshot.
  This is the sole exception to the planned no-existing-test-edits policy;
  rerouting imports through unrelated owners to hide the count was rejected.
* The new alignment characterization initially assumed `Alignment.start` meant
  the start of the matched suffix. The existing algorithm documents the end of
  that suffix: prepending includes known rows which the repository deduplicates.
  Corrected the new test before extraction; no production alignment change.
