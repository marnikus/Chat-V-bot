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
  `UndoService._commit_timeline` compares the archive tokens it carries before
  and after each commit; every token that just left (the `MAX_STACK_HISTORY`
  cap, or a new edit truncating the redo branch) is handed to
  `HistoryMutateService.purge_tokens()`, which erases the hidden messages and
  the tombstoned person for good and says so in the log.
* **The app closes ⇒ the trash is destroyed.** `HistoryMutateService
  .begin_session()` runs on every world open: it compares the world’s stored
  `session` meta against this run’s `SESSION_TOKEN` (a fresh uuid4 per
  process). A different token means “a previous run left this trash behind”,
  so `forget_old_trash()` erases the hidden rows, the tombstones **and** the
  now-unreachable `kind='archive'` rows in the world’s `undo_history` table,
  then stamps this run. A mid-session re-init, a restart or a switch back to a
  world this run already opened sees its own token and does nothing.
* Switching *away* from a world is not a close: that world keeps its trash
  until it is opened again — by which time another run's token makes it
  garbage. `sync_world_state` merges timelines with `purge_dropped=False`, so
  the world being left is never the one whose rows get erased.

The People-list half needs none of this: a queue row carries no history, so
restoring it from a surviving `people` entry is always honest.

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
| `PersonLifecycle.purge_deleted` | 17 LOC | **19 LOC** (the row work extracted to `_delete_hidden` / `_sweep_tombstones` / `_drop_person`) | 30 LOC; only private helpers added to the class |
| `HistoryMutateService.save_world_undo` | 12 LOC, 1 statement per entry, no retry | **19 LOC** in one transaction + `_write_world_undo` (9 LOC) | 30 |
| `HistoryMutateService.begin_session` / `forget_old_trash` / `purge_tokens` (new) | — | 14 / 16 / 26 LOC, CC ≤ 6 | 30 / CC 10 |
| `UndoService._commit_timeline` | 24 LOC | **20 LOC** (identity stamping and the store split extracted to `_stamp_seq` / `_store_timeline`) | 30 |
| `UndoService._purge_tokens` / `_dropped_tokens` (new) | — | 20 / 5 LOC | 30 |
| `HistoryDB.close()` | released the turn before committing | commits first, drops the turn last | — |

`stores/world_lock.py` is a leaf (no Qt, no `backend/`/`services/` imports) and
223 lines including its rationale. No function was split to game LOC: every
extraction names a step of the workflow, and the undo path is *more*
verifiable than before, not less.

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
