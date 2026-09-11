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
(`ArchiveCommands`, 7 methods / 82 LOC) around module-level helpers that name
one fact each — `_rows`, `_apply`, `_state`, `_disagrees` (+
`_person_verdict` / `_row_verdict`), `_reason`, `_outcome`. `UndoService` keeps
only the scheduling (`_apply_archive_command`, `_spawn`, `_crash_log`) and the
timeline rewind (`rewind_after_failure`, `_position_of`). Extracting the two
snapshot branches out of `apply_command` also took that legacy function from
27 LOC / CC 12 to 15 LOC / CC 6.

Tick after it ran, and the silent-crash hole is closed: `_spawn` attaches a
done-callback (`_crash_log`) to every background step the undo service starts,
so a task that dies can no longer disappear without a trace.

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

### 2.4 Deletion safety

* The DB window’s 🗑 asks first (`window.Dialog.confirm`, the same modal the
  Person History window uses) and states that Ctrl+Z restores both halves.
* The soft delete stays the only thing a click can do; the permanent path is
  the explicit **Empty trash** button in the DB window’s footer, confirmed in
  the same modal, which calls the existing `history_purge_deleted` slot
  (now also erasing tombstoned *persons*, not only hidden messages) —
  `HistoryMutateService.purge_trash()`. Ctrl+Z cannot bring those back, and the
  log line says so.

## 3. Measurements (RULE 16 / RULE 18)

Measured with `tools/metrics/rule16_gate.py` / the same `measure_function`
against the finished tree:

| Symbol | Before | After | Limit |
|---|---|---|---|
| `UndoService._apply_archive_command` | 37 LOC, CC 10, cog 22 | **17 LOC, CC 5, cog 4** | 30 / 10 / 15 |
| `UndoService.apply_command` | 27 LOC, CC 12 | **15 LOC, CC 6** (two extractions) | 30 / 10 |
| `UndoService.undo` / `redo` | 29 / 24 LOC | unchanged (29 / 24) | 30 |
| `ArchiveCommands` (new class) | — | 7 methods, 82 LOC, no function over 21 LOC | 15 methods / 150 LOC |
| new helpers (`_position_of`, `_spawn`, `_crash_log`, `_disagrees`, `_row_verdict`, …) | — | 4–19 LOC, CC ≤ 6, cog ≤ 9 | 30 / 10 / 15 |
| `WorldGate` / `WriteTurn` (new) | — | 5 + 4 methods, 48 + 23 LOC, longest method 17 LOC | 15 / 150 |
| `HistoryBridge` class (ratchet) | 486 LOC / 45 methods | **488 / 45** | 493 / 45 frozen — LOC only |
| `PersonLifecycle.purge_deleted` | 17 LOC | **29 LOC**, same method count (18) | 30 LOC; no method added to an over-15 class |
| `HistoryMutateService.save_world_undo` | 12 LOC, 1 statement per entry, no retry | **19 LOC** in one transaction + `_write_world_undo` (9 LOC) | 30 |
| `HistoryDB.close()` | released the turn before committing | commits first, drops the turn last | — |

`stores/world_lock.py` is a leaf (no Qt, no `backend/`/`services/` imports) and
223 lines including its rationale. No function was split to game LOC: every
extraction names a step of the workflow, and the undo path is *more*
verifiable than before, not less.

## 4. Tests

* `tests/test_world_write_gate.py` (new, 17 tests) — the gate itself
  (classification, one gate per file, same-token re-entrance, cross-token
  waiting, fail-open after `WAIT_S`, locked-error retry) plus the end-to-end
  reproduction on the real stack: a slow `UserMemory.replace_all` running
  beside `repo.restore_person` (README: the archive write must wait for the
  open transaction — verified by a timeline of the two commits), the queue
  write waiting for a held `HistoryDB` turn, a failed statement giving the turn
  back, delete → undo restoring person **and** history with the verified log
  line, redo hiding them again, a refused undo (LOCKED `restore_person`)
  reporting `❌ Undo failed` and staying retryable, the DB window’s
  `userdb_changed` event following the verified state, and “Empty trash”
  (soft delete remains reversible until the purge erases the tombstone; a
  later Ctrl+Z reports the failure instead of pretending).
* `tests/test_history_repo_lifecycle.py` (extended) — `purge_deleted()`
  erases tombstoned persons while a living person survives, and a
  single-nick purge leaves the other tombstone alone.
* `tests/test_userdb_refresh.js` (new, Node) — the real `history-db.js`
  against the real ids from `ui/index.html`: one reload per burst of live
  changes (and the scroll position kept), named changes reloading at once, the
  remove-confirm asking first and doing nothing when refused, Empty trash
  purging the whole trash only after confirmation, and the headless fallback.
* `tests/test_archive_delete_undo.py`, `tests/test_people_undo.py`,
  `tests/integration/services/test_services_undo.py` — unchanged contracts
  (kind/value payloads, one global timeline, `wait_for(self.changed)`); all
  still green after the verified-command rewrite.

**Mutation check (RULE 8).** Reverting the fix in-process (gate inert + no
`busy_timeout`) makes 7 of the 17 Python tests fail, including all three
cross-connection ones; with the connections’ own `busy_timeout` left in place
(the pre-fix world had 5 s of `sqlite3` default waiting) the tests still pass,
which is why the collision tests set `PRAGMA busy_timeout=0` — they must pin
the gate, not SQLite’s default patience.

