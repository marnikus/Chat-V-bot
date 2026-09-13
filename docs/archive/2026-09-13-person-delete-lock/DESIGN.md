# Person delete / restore lock — design (2026-09-13)

User report: delete → undo reports archive/189 People rows restored → subsequent
person deletion and history clear repeatedly fail with `database is locked`.
Scope is this regression, not another Collector/UndoService refactor.

## Research and reproduction

HistoryDB and UserMemory use distinct aiosqlite connections to the same world.
Archive lifecycle methods already commit their recounts; adding another commit
there or increasing busy_timeout would not repair a leaked queue transaction.
UserMemory.upsert_user does SELECT followed by INSERT/UPDATE without rollback on
error. Other queue writes also lack exception/cancellation cleanup. replace_all
only rolls back Exception during its insert loop, not the initial DELETE or
CancelledError. Concurrent queue methods share one connection and can commit
one another's partial work. Undo currently schedules archive/People restoration
as separate tasks, alongside background collection and undo-history persistence.

A real-file reproduction injected a SQLite ABORT trigger on a queue UPDATE:
upsert_user raised IntegrityError; UserMemory._db.in_transaction remained True;
a subsequent real HistoryRepo.delete_person raised `database is locked` on the
other connection (50 ms busy timeout for the test only). This reproduces the
failure mechanism, not proof of the exact originating exception in the user's DB.

## Selected correction

* Add a small store-local serialized-write decorator, using one asyncio.Lock per
  UserMemory. Cover every primitive queue mutation, including the full snapshot
  replacement; do not wrap upsert_many around already-guarded upsert_user calls.
* Keep successful commits at their existing method boundaries. On any failure,
  including cancellation, roll back before releasing the lock and re-raise.
  Do not auto-commit every SQL statement or roll back another active writer.
* Replace upsert's check-then-insert with INSERT ... ON CONFLICT(nick) DO NOTHING,
  then update existing-row discovery fields. Preserve new/known results and
  existing messaged/count/notes/timestamps semantics. Do not use blanket OR IGNORE
  to hide invalid rows or other constraints.
* Centralize replace_all's cleanup in the same guard. Maintain an all-or-nothing
  snapshot and preserve public signatures. Add no new methods to the legacy class;
  the smaller upsert/replacement bodies offset the guard wiring.
* No schema changes, lock timeout increase, row deletion to repair a database,
  application-wide autocommit, or collector queue-ownership policy change.

## Evidence required

Tests use real UserMemory + HistoryDB/HistoryRepo against one temporary world,
not separate queue/archive files or mocked SQL results. Cover failed upsert,
failed initial replacement DELETE, insert failure, cancellation after DELETE,
serialized replacement vs discovery and SQLite constraint fidelity. Verify another
connection can write immediately after failure and original queue rows survive.
Exercise real bridge delete/clear/restore and global undo/redo repeatedly with
189 queue rows and concurrent discovery, asserting both stores and persisted data,
not just optimistic UI log messages. Existing archive/queue tests remain intact.

Run changed-code structure/smell/clone gates and full branch coverage against the
previous baseline; preserve RULE 16 caps and RULE 18 context ceilings. Write results
separately and update existing current-doc rows without increasing their length.

## Boundaries / remaining risks

This does not redesign the synchronous undo API's optimistic timeline/logging,
make two connections one atomic transaction, or supervise world-switch/close races.
It prevents queue transaction leaks and serializes one connection's writers;
external applications can still lock a database. Collector's known RULE 14 queue
admission issue remains separately queued. A running process with an already-leaked
transaction should be restarted normally after installing the fix; do not remove
WAL/SHM files or delete user data to unlock it.
