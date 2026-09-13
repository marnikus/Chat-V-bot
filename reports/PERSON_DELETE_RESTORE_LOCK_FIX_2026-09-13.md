# Person delete / restore lock — fix and verification

2026-09-13 · branch `arena/01a093f4-chat-v-bot` · base `4cc7013`.

**Fixed locally:** two reproduced SQLite locking mechanisms affecting person
removal, undo/restore and subsequent history clears. No user database was modified
in this workspace; all reproductions used temporary real SQLite world files.

Design notes: [initial investigation](../docs/archive/2026-09-13-person-delete-lock/DESIGN.md),
[cursor interleaving](../docs/archive/2026-09-13-person-delete-lock/CURSOR_INTERLEAVING.md),
[final compatibility decisions](../docs/archive/2026-09-13-person-delete-lock/COMPATIBILITY_REVIEW.md).

## What caused the reproduced failures

The archive and People queue have separate async connections to the **same**
world file. Tests using an archive alone or a separate queue file missed this.

1. **Leaked queue write transactions.** Failed queue writes could leave SQLite's
   implicit transaction open. Cancelling a full People-list replacement had the
   same problem. Another connection then failed to delete the archive person
   with `database is locked`. Concurrent queue mutations could also interleave
   with a partially restored snapshot and raise duplicate-nick errors.
2. **Archive read/write interleaving.** A read cursor could remain active while
   another task started a write on that same connection. If undo committed the
   queue snapshot in between, SQLite could not upgrade the archive's older WAL
   snapshot: **SQLITE_BUSY_SNAPSHOT**. That failed write left an explicit
   transaction open, so later deletes and clears kept failing. Increasing the
   timeout would not repair that snapshot.

Both mechanisms were reproduced independently. The actual bridge/global-undo
sequence with a shared database also failed before the second correction. The
original user database was not available, so this does not claim which exception
first poisoned that particular running process.

## Changes

Only two production files changed:

* `stores/user_memory.py`: a private serialized-write guard covers all eight
  primitive queue mutators. Failures—including cancellation—roll back before
  another writer is admitted. Full snapshot replacement remains all-or-nothing;
  bulk discovery calls the guarded primitive without a nested-lock deadlock.
* Queue upsert is one conditional `INSERT ... SELECT ... WHERE NOT EXISTS`, then
  an existing-row metadata update when needed. It preserves new/known results,
  existing message flags/counts/notes and works with pre-migration tables lacking
  UNIQUE(nick). It does not silently ignore unrelated constraints.
* `stores/history_db.py`: private `_HistoryAccess` serializes statement access,
  including execute/fetch/**close** for a read cursor. Cancelled acquisition reaps
  and closes the worker's cursor before releasing access. Existing mutation
  owners retain their commit boundaries; autocommit was not enabled.

No schema change, database cleanup, retry/timeout increase, public signature
change or application-wide transaction redesign. The helpers stay beside their
sole owners, preserving the existing 36-file stores package ceiling.

## Regression evidence

Added **18 tests** using real SQLite connections, real services and real bridge
slots. Event barriers reproduce interleavings without timing sleeps.

* Failed upsert; failed replacement DELETE/INSERT; failed mark/delete/reset/clear
  operations; invalid rows; cancellation after a replacement DELETE.
* Immediate writes through the archive connection after each failed queue write,
  with original queue data intact and no leaked transaction.
* Concurrent discovery cannot enter an uncommitted replacement; discovery and
  restoration preserve existing message flags/counts/notes.
* Archive UPDATE waits for the read cursor to close after the queue commits;
  cancellation cannot abandon a newly opened cursor.
* **189 People rows**, repeated three times: real person delete → undo → redo →
  undo → history clear → undo, both with and without concurrent discovery.
  Both stores are asserted, and a fresh SQLite connection verifies durable state
  and immediate writer access—not merely optimistic “restored” log messages.

The final 18-test regression suite passed **three consecutive runs** (1.17 s,
1.17 s, 1.16 s). Existing tests were not edited or weakened. The full suite caught
a legacy-schema incompatibility and the package file-count excess in the first
implementation; both were corrected rather than changing their tests.

## Final validation

| Check | Result |
|---|---|
| Full suite through the changed-code/coverage gate | **2916 passed**, 3 skipped, 1 deselected, 1 xfailed; 774 subtests; 378.53 s |
| Focused compatibility selection | **66 passed**, 227 subtests |
| New regression suite | **18 passed**, repeated three times |
| JavaScript harnesses | **25 files passed** |
| General structure, unused code/imports, clones, tests/coverage | **All passed**, no breaches or tool errors |
| Historical feature gate with clones | Passed |
| Public API / stores layering / package size checks | Passed unchanged |

Standalone Pylint still flags seven existing schema re-export imports in
HistoryDB; they are unchanged compatibility exports. The differential smell gate
reports zero new findings, rather than claiming those historical warnings vanished.

| Coverage | Before | After |
|---|---:|---:|
| Lines | 13534 / 14838 = 91.21175% | **13588 / 14881 = 91.31107%** |
| Branches | 3125 / 3634 = 85.99340% | **3135 / 3636 = 86.22112%** |

The machine-readable coverage baseline is ratcheted **up** to these verified
counts. All nine new function bodies are exercised. The existing single
unawaited collector-push warning remains; live Chrome/WebEngine and mutation
were not newly validated. The exact real-WebEngine test remains deselected.

RULE 16: HistoryDB class **235 → 224 LOC**, still 30 methods; UserMemory stays
**207 LOC / 21 methods**. No legacy class axis grows. New `_HistoryAccess` is
**42 LOC / 7 methods**; new helpers have maximum LOC 15, params 3, CC 3,
cognitive 2, nesting 2. No quality override, golden rewrite or threshold increase.
RULE 18: UserMemory file 282 lines; HistoryDB 306 (six above the preference).
The latter keeps one connection's access/lifecycle code together rather than
adding tiny files beyond the existing module budget. Current-doc ceilings remain
unchanged: SYSTEM_OF_RECORD 305 lines; docs map 81 lines.

## Applying the fix / limits

After installing the updated code, **restart the app normally** so any already
poisoned connection closes. Do not delete the database, WAL or SHM files to unlock
it. No data-repair SQL or removal of archived messages is part of this fix.

This does not turn queue/archive mutations into one cross-connection transaction,
redesign the synchronous undo API's optimistic timeline/logging, or resolve the
separate Collector queue-admission policy issue. External programs can still
hold SQLite locks. Hosted quality CI remains inactive pending authorized
activation. This report does not claim a commit or push of the fix.

Workspace evidence: `/home/user/person-delete-debug/` contains `red.log`,
`cursor-red.log`, `cancel-cursor-red.log`, `regressions.log`, `compatibility.log`,
`repeated.log`, `full-gate-first.json`, `full-gate.json`, `historical-gate.log`
and `node.log`. Temporary coverage output is private to the gate; its final JSON
retains the real test summary, verified source binding and separate ratios.
