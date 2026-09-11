# Delete in the DB window, Ctrl+Z, and the “database is locked” that ate it

**Bug report (2026-09-11):** deleting a person in the Full User Database and
pressing Ctrl+Z logs

```
[01:05:13] 🗑 “Mloni” and their history removed — Ctrl+Z restores both
[01:05:17] ↩ Undo — archive restored
[01:05:17] ↩ People list restored — 189 person(s)
[11:17:16] WARNING undo save to D:\Google Drive\Chat V Bot\v.db failed: database is locked
```

…while the person never comes back in the database view. In the People list
the same workflow works.

Status: fixed. This file is the reasoning; the spec lives in
`docs/current/SYSTEM_OF_RECORD.md`.

---

## 1. What actually happens (reproduced, not guessed)

`tests`-style reproduction with the real wiring (`UserMemory` + `HistoryService`
on ONE world file, real bridge, real undo timeline); the script is the same
shape as `tests/test_world_write_gate.py`:

```
BEFORE delete  DB: ['Mloni']        list: ['Mloni', 'Other']
--- delete from DB window ---       DB: []   list: ['Other']
history: [('archive', 'delete_person')]
--- Ctrl+Z ---
undo result: {"kind": "archive", ...}          ← claims success
after undo DB: []                              ← still gone
after undo list: ['Mloni', 'Other']            ← list DID come back
person row: deleted_at='…'  visible messages: 0
```

and, with the event loop's exception handler installed, the reason:

```
Task exception was never retrieved
  stores/history_repo_lifecycle.py:180 in _restore_rows  →  UPDATE messages …
sqlite3.OperationalError: database is locked
```

Two independent defects, one visible failure:

1. **`UndoService._apply_archive_command` scheduled its work and returned
   `True` immediately.** The coroutine had no error handling, so the
   exception above had nowhere to go — the timeline moved, `undo()` logged
   “archive restored”, and the tombstone stayed. The People half of the same
   entry (`PeopleService.apply`, also scheduled) did land, which is exactly the
   inconsistency the report describes: restored in the list, deleted in the DB.
2. **Two connections write the same world file.** `UserMemory._db`
   (the `users` queue) and `HistoryDB._conn` (persons / messages /
   `undo_history`) are separate `aiosqlite` connections onto the same `.db`
   (RULE 14, One DB = One World). SQLite allows one writer per file, and a
   connection that has already read cannot even wait for the lock — it fails
   *immediately* with `database is locked` (the WAL snapshot case). Measured:
   raising `PRAGMA busy_timeout` to 20 s does **not** help, because the busy
   handler is not consulted on that path. The undo of a person delete is the
   perfect storm: it rewrites the whole people list (`DELETE FROM users` +
   189 inserts) on one connection while restoring the person’s rows on the
   other.

The same race explains the second half of the report (“it gives an error and
refuses to delete the person”): the delete path *also* interleaves those two
connections, and its failure reaches the UI as
`⚠ history_delete_person: database is locked`, after which the row visibly
stays in the list.

## 2. Design

### 2.1 One write gate per world file — `stores/world_lock.py` (new)

A per-file, **per-connection-token** re-entrant async gate:

* `gate_for(path)` — the single gate every connection to that file shares
  (keyed by `realpath`);
* `WorldGate.enter(token)` / `leave(token)` — the turn belongs to a
  *connection*, not to a task: the same token may enter again (a guarded
  operation calls other guarded ones), a different token waits;
* `WriteTurn(token, path)` — `begin()` on the first write statement, `end()`
  on commit/rollback, `drop()` when the connection closes or a statement
  fails; the `held` flag makes `begin()` idempotent per transaction, so one
  commit gives the turn back exactly once;
* `world_write(path, token=None)` — a whole-transaction context manager
  (used by `UserMemory`);
* `retry_locked(work)` — bounded retry for a lock held by something *outside*
  the process (Google Drive sync, antivirus, a second instance);
* `is_locked_error(exc)`, `is_write_sql(sql)`, `apply_busy_timeout(conn)`.

**The first draft counted levels per task** (`_held[task]`) and released one
level per commit — but a transaction spans several write statements, so the
archive connection was left holding six levels after one seeding pass, and
`delete_person` then deadlocked against itself (`tests/test_archive_delete_undo.py`
stalled after six tests). The token + `WriteTurn.held` model above replaced it;
do not return to balanced enter/leave arithmetic around individual statements.

Wiring: `HistoryDB.execute()`/`executemany()` take the turn for a write
statement and `commit()`/`rollback()` end it, so the gate is held for exactly
the connection's transaction. `UserMemory` wraps its eight write methods in
`async with world_write(self._db_path, self._db)`. Reads are never gated, so a
read never waits.

*Fail-open, bounded*: the gate waits at most `WAIT_S = 15 s` for its turn,
then logs a warning and continues **without** it (a bug that forgets a commit
must not freeze the queue forever; the worst case is then SQLite’s own
`database is locked`, i.e. the behaviour before this change). `retry_locked`
is what survives the snapshot-upgrade case: the whole operation is re-run on a
fresh snapshot.

**Rejected as dishonest reductions:** (a) only raising `busy_timeout` — does
not apply to the snapshot case, measured; (b) retrying without the gate — it
turns a deterministic deadlock into a probabilistic one; (c) moving all queue
writes onto the archive connection — a larger change to world switching, which
the switch/deletion suites pin; (d) sharing one `asyncio.Lock` **around single
statements** — a transaction spans statements, so it would not exclude anyone.

### 2.2 An archive command is a task that must prove itself

`UndoService._apply_archive_command` now schedules ONE task that

1. applies the People half and the archive half in order (`PeopleService.apply`
   first, so the list cannot end up restored while the rows stay hidden);
2. runs the repository call through `retry_locked(...)`;
3. **reads the database back** (`HistoryQuery.person_stats` → `deleted`,
   `hidden`, `messages`) and compares it with the state captured before the
   call — `archive restored` is logged only when the read-back agrees;
4. on failure: logs `❌ Undo failed — …`, re-applies the People half of the
   *other* direction (so the list returns to the state the archive is in), and
   puts the timeline pointer back on (undo) / behind (redo) the entry so Ctrl+Z
   can simply be pressed again.

Text of the successful undo (replaces the unconditional “archive restored”):

```
↩ Undo — “Mloni” is back in the database (4 message(s))
↪ Redo — “Mloni” removed again (4 message(s) hidden)
```

**Where the code lives:** the orchestration in `services/undo_archive.py`
(`ArchiveCommands`, 7 methods / 84 LOC) around module-level helpers that name
one fact each — `_rows`, `_apply`, `_state`, `_disagrees` (+
`_person_verdict` / `_row_verdict`), `_reason`, `_outcome`. `UndoService` keeps
only the archive entry point (`_apply_archive_command`) and the timeline rewind
(`rewind_after_failure`, `_position_of`). Extracting the two snapshot branches
out of `apply_command` also took that legacy function from 28 LOC / CC 12 to
15 LOC / CC 6.

The silent-crash hole is closed one tick after the task runs: `spawn` (on
`services/undo_timeline.py::TimelineCommit`) attaches a done-callback
(`_crash_log`) to every background step the undo timeline starts, so a task
that dies can no longer disappear without a trace.

### 2.3 The DB window refreshes itself

`The Full User Database` window already reloads on `userdb_changed`; the
emitters were missing:

* live append (collector/heartbeat) → `app.js` routes the existing
  `history_appended` signal to `HistoryDb.liveChanged('appended')`, which
  debounces 400 ms and keeps the scroll position, so a live archive does not
  yank the list around;
* label edits → `labels_changed` also calls `HistoryDb.liveChanged('labels')`,
  because the label pills live in this table too;
* delete / clear / undo / redo / world switch already emitted the event — the
  undo one now fires after the verified change instead of before it.

### 2.4 Delete safety — no dialogs, a session-sized trash

The first cut of this design asked before every delete (a confirm dialog) and
offered an **Empty trash** button for the irreversible step. The user rejected
both the same day: *“i dont need any cofirmations to delete perrson or chat in
DB … asking to support the delete person with function undo (so it keeps track
data deleted and able to add back to DB but as soon it closed or it above undo
memory steps it losed completely then).”* The dialog and the button are gone.

What replaces them is a rule with one sentence: **the trash lives exactly as
long as the undo step that can restore it.**

* 🗑 in the DB window (and Delete in the People list) deletes **immediately** —
  no confirm, no extra click. The row leaves the list the same moment.
* The delete is still a *soft* one: the person is tombstoned and their
  messages are hidden under one token, invisible everywhere and restorable by
  Ctrl+Z — the safety net is the undo timeline, not a dialog.
* **The step falls off the timeline ⇒ the data is destroyed.**
  `services/undo_timeline.py::TimelineCommit.commit` compares the archive
  tokens the timeline carries before and after each commit; every token that
  just left (the `MAX_STACK_HISTORY` cap, or a new edit truncating the redo
  branch) is handed to `services/history/trash.py::purge_tokens()`, which
  erases the hidden messages and the tombstoned person for good and says so in
  the log.
* **The app closes ⇒ the trash is destroyed.** `trash.begin_session()` runs on
  every world open: it compares the world’s stored `session` meta against this
  run’s `SESSION_TOKEN` (a fresh uuid4 per process). A different token means
  “a previous run left this trash behind”, so `forget_old_trash()` erases the
  hidden rows, the tombstones **and** the now-unreachable `kind='archive'`
  rows in the world’s `undo_history` table, then stamps this run. A mid-session
  re-init, a restart or a switch back to a world this run already opened sees
  its own token and does nothing. The open / switch paths call it through
  `trash.open_world()`, which turns a failed sweep into a warning instead of a
  world that will not open; `WorldSwitcher._load_world_state()` calls it too,
  so a world switched into mid-session is swept before anything reads it.
* Switching *away* from a world is not a close: that world keeps its trash
  until it is opened again — by which time another run's token makes it
  garbage. `sync_world_state` merges timelines with `purge_dropped=False`, so
  the world being left is never the one whose rows get erased.

The People-list half needs none of this: a queue row carries no history, so
restoring it from a surviving `people` entry is always honest.

## 3. Measurements (RULE 16 / RULE 18)

Measured with `tools/metrics/rule16_gate.py` (`measure_function` / `classes` —
the AST span the gate itself fails on). *First cut* = `883ff8f`, the shipped
slice; *close-out* = this change; *baseline* = `3fc511b`, the commit the
feature started from.

### 3.1 The close-out — RULE 18 ideals on the code this feature wrote

The first cut fit RULE 16's hard limits but grew files and classes that were
already over RULE 18's ideals (§16.5 forbids making a legacy offender worse).
The close-out moved each theme out of the file that had outgrown it:

| Where | First cut (883ff8f) | Close-out |
|---|---|---|
| `services/history/mutate.py` | 291 lines, class 268 LOC / 19 methods | **196 lines, class 160 LOC / 12 methods** (baseline 177 / 163 / 12) — the trash theme moved to `trash.py`, the transactional writer to module-level `_write_world_undo` (9 LOC) + `_undo_rows` (7) |
| `services/history/trash.py` (new) | — | 129 lines, **no class**: `begin_session` 7, `_trash_persons` 8, `open_world` 11, `purge_trash` 12, `forget_old_trash` 15, `purge_tokens` 24 LOC (CC ≤ 6); `HistoryService` keeps the four public entry points as one-line delegates in `__init__.py` (the §16.0 facade row) |
| `services/history/runtime.py` | 296 lines, 5 collaborators | **233 lines, 4** — `HistoryMigration` moved to `migrate.py` (92 lines) when the file hit the 300-line mark; `WorldSwitcher` is 107 / 7, its new `load_labels` (9 LOC) de-duplicates the init and reload paths |
| `services/history/export.py` | 160 lines, class 142 / 21, `init` 46 LOC / CC 12 / cog 12 | **154 lines, class 133 / 21, `init` 37 LOC / CC 9 / cog 8** — `init` is back below the 39 LOC it had at the baseline (it was a §16.5 landmine): the closed-session sweep is one `open_world(self)` — the guard lives in `trash.py` — and the world's label load is one `WorldSwitcher.load_labels` (the init and the switch path now share it) instead of the 7-line block each used to carry |
| `services/undo_service.py` | 664 lines, `UndoService` 524 LOC / 39 methods | **561 lines, class 399 LOC / 26 methods** (baseline 563 / 444 / 28) — `services/undo_timeline.py::TimelineCommit` owns commit + store split + dropped-token purge + task spawning; `_log_command` 8, `_apply_people_command` 7, `_apply_labels_command` 11 became module-level beside `_values_equal` / `_same_entry` / `_position_of` |
| `services/undo_timeline.py` (new) | — | 146 lines, `TimelineCommit` 104 LOC / 10 methods: `commit` 21 (CC 5), `_purge_tokens` 20, `_store_timeline` 13, everything else 2–8 LOC |
| `stores/history_db.py` | 305 lines, class 266 LOC / 31 methods | **300 lines, class 232 LOC / 30 methods** (baseline 272 / 235 / 30) — `init` back to its baseline 54 LOC, `close` 19 → 8, `commit` 5 → 2; the new plumbing is module-level `_gated` 10 / `_release` 6 / `_closed` 8 |
| `stores/user_memory.py` | 274 lines, class 228 LOC / 21 methods | **267 lines, class 213 LOC / 21 methods** (baseline 256 / 218 / 21) — `world_lock.world_transaction` commits and releases the turn for every write site, so no method spells either out; `replace_all` 40 → 35 LOC (CC 14 → 13, cog 18 → 17) |
| `stores/world_lock.py` | 214 lines | 241 lines — `world_transaction` 16 LOC / CC 3 / cog 1 + `_rollback` 6 |
| `stores/history_repo_lifecycle.py` | 421 lines, class 399 / 21 | **418 lines, class 367 / 18** (baseline 390 / 368 / 18) — the erase steps became module-level `_delete_hidden` / `_erase_person` / `_erase_tombstones`; the file stays above 300 on purpose: §18.2 asks for the second responsibility and the person lifecycle *is* the one this file owns, while the class itself is now at its baseline |
| `bridge/history_bridge.py` | 530 lines, class 488 LOC / 45 methods | **528 lines, class 486 LOC / 45 methods** (= the 3fc511b baseline, ratchet 493 / 45) — the unused "empty trash" bridge slot hands back to the world store's own `purge_deleted`, so the landmine shrinks instead of growing |
| `services/history/__init__.py` | 48 lines, `HistoryService` 23 LOC / 1 method | 62 lines, `HistoryService` 36 LOC / 5 methods — `__init__` plus the four one-line trash delegates |

**Clone baseline.** The extraction removed two exact-AST groups (import-header
windows: `app/lifecycle.py` ↔ `services/history/export.py`, and
`services/history/mutate.py` ↔ `services/undo_service.py`) and left one new
header window (`services/history/query.py` ↔ `services/undo_service.py`,
because `undo_service.py` no longer imports `asyncio`). `CLONE_BASELINE` in
`tools/metrics/rule16_gate.py` (11 entries) carries that history in its
comment — the same treatment the pre-existing `db_bridge` ↔ `history_bridge`
header already had; the scan reports 11 groups / 83 lines. No *logic* is
cloned anywhere.

### 3.2 The hot spots, before and after

| Symbol | 3fc511b | Close-out | Limit |
|---|---|---|---|
| `UndoService._apply_archive_command` | 37 LOC, CC 10, cog 22 | **17 LOC, CC 5, cog 4** | 30 / 10 / 15 |
| `UndoService.apply_command` | 28 LOC, CC 12, cog 15 | **15 LOC, CC 6, cog 5** (two extractions) | 30 / 10 / 15 |
| `UndoService.undo` / `redo` | 30 / 25 LOC | 29 / 24 LOC | 30 |
| `ArchiveCommands` (new class) | — | 84 LOC, 7 methods, longest 21 LOC | 150 / 15 |
| `WorldGate` / `WriteTurn` (new) | — | 53 LOC / 5 methods and 25 / 4, longest method 17 LOC | 150 / 15 |
| `HistoryBridge` class (ratchet) | 486 LOC / 45 methods | **486 / 45** | 493 / 45 frozen |
| `PersonLifecycle.purge_deleted` | 17 LOC | **19 LOC** — the row work extracted to `_delete_hidden` / `_erase_person` / `_erase_tombstones` | 30 |
| `HistoryMutateService.save_world_undo` | 12 LOC, CC 8 | **9 LOC, CC 3, cog 2** — one `retry_locked` call on `_write_world_undo` (9) + `_undo_rows` (7) | 30 / 10 |
| `TimelineCommit.commit` (new) | `_commit_timeline` 20 LOC | 21 LOC, CC 5 — identity stamping, store split and the dropped-token purge are their own methods | 30 |
| `TimelineCommit._purge_tokens` / `_dropped_tokens` (new) | — | 20 / 5 LOC | 30 |
| `HistoryDB.close()` | 12 LOC, released the turn before committing | **8 LOC** — commits first, drops the turn last | 30 |
| `HistoryDB.commit()` | 2 LOC inline | **2 LOC** delegating to `_release` (commit + turn back on every path) | 30 |
| new helpers (`_position_of`, `spawn`, `_crash_log`, `_disagrees`, `_row_verdict`, `_person_verdict`, …) | — | 4–24 LOC, CC ≤ 6, cog ≤ 9 | 30 / 10 / 15 |

The gate (`tools/metrics/rule16_gate.py --with-clones`) exits **0** on the
finished tree: every owned function fits, the ratchet holds, no override is
stale, and the clone scan reports 0 new groups and 0 stale baseline entries.
An independent diff audit (every changed file, class and function against
`3fc511b`) reports **`problems: 0`** — the only remaining findings are the
`legacy over:` annotations that were already there at the baseline, on the
same or smaller values.

## 4. Tests

* `tests/test_world_write_gate.py` (new, 30 tests) — the gate itself
  (classification, one gate per file, same-token re-entrance, cross-token
  waiting, fail-open after `WAIT_S`, locked-error retry), the pure facts the
  log is built from, and the end-to-end reproduction on the real stack:
  a slow `UserMemory.replace_all` beside `repo.restore_person` (the archive
  write must wait for the open transaction — verified by a timeline of the two
  commits), the queue write waiting for a held `HistoryDB` turn, a failed
  statement giving the turn back, delete → undo restoring person **and**
  history with the verified log line, redo hiding them again, a refused undo
  reporting `❌ Undo failed` and staying retryable, a refused *people* half
  stopping the whole command, a People-only entry saying so, the DB window’s
  `userdb_changed` event following the verified state, and the session-sized
  trash (`TestTrashLifecycle`): reversible while the session runs, erased on
  the next app run (with the stored session stamp re-written and no archive
  entry left behind), erased when the step falls off the cap, and never
  claimed as a restore afterwards.
* `tests/test_history_repo_lifecycle.py` (extended) — `purge_deleted()`
  erases tombstoned persons while a living person survives, and a
  single-nick purge leaves the other tombstone alone.
* `tests/test_userdb_refresh.js` (new, Node) — the real `history-db.js`
  against the real ids from `ui/index.html`: one reload per burst of live
  changes (and the scroll position kept), named changes reloading at once, the
  footer carrying no trash button, **no confirmation dialog on a person
  delete** (the call reaches the backend on the first click), and no purge
  path inside the window at all.
* `tests/test_archive_delete_undo.py`, `tests/test_people_undo.py`,
  `tests/integration/services/test_services_undo.py` — unchanged contracts
  (kind/value payloads, one global timeline, `wait_for(self.changed)`); all
  still green after the verified-command rewrite.

**Mutation check (RULE 8).** Reverting the fix in-process (gate inert + no
`busy_timeout`) makes 7 of the 30 Python tests fail, including all three
cross-connection ones; with the connections’ own `busy_timeout` left in place
(the pre-fix world had 5 s of `sqlite3` default waiting) the tests still pass,
which is why the collision tests set `PRAGMA busy_timeout=0` — they must pin
the gate, not SQLite’s default patience.
