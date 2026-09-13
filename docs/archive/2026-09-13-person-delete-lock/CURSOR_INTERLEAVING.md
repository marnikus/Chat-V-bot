# Shared-world follow-up: active read cursors (2026-09-13)

Design addendum BEFORE implementing the second correction. Queue rollback and
serialization make the seven first regressions pass, but the real bridge test
still fails, even without background discovery. Old archive tests predominantly
use no queue connection or separate queue/archive files.

## Confirmed second mechanism

HistoryDB fetch helpers await execute → fetch → close in separate steps. Another
task can start a write on that SAME connection between those steps. If the queue
connection commits its undo snapshot while the archive read cursor is open, the
archive write cannot upgrade its stale WAL read snapshot. A real SQLite probe
reports `database is locked`, `SQLITE_BUSY_SNAPSHOT`, in_transaction=True. Closing
the cursor afterward does not end the explicit transaction created by the failed
write. Later deletes/clears remain poisoned. Busy timeout does not fix this.

## Correction

Add stores/history_access.py, a small connection-access collaborator. One lock
covers each write/commit operation and the WHOLE read-cursor execute/fetch/close
lifetime. HistoryDB's existing public helper signatures and tuple/dict/Row return
shapes remain adapters; its connection/schema lifecycle stays where it is.
No autocommit, transaction-wide schema redesign or hidden commit/rollback in the
access layer. Existing mutation owners keep their successful commit boundaries.
Calls using raw .conn remain internal initialization/explicit low-level APIs;
normal UI/repository queries use the protected helpers.

Regression: pause a real SELECT cursor, commit a queue write through the other
connection, submit an archive UPDATE, prove the UPDATE does not enter SQLite
until the read cursor closes, then verify success. This uses events, not sleeps.
The shared-world bridge delete/undo/redo/clear test with 189 people must pass with
and without concurrent discovery; no relaxation of its persistence assertions.

This extends the first design based on actual failed end-to-end evidence. It does
not claim all domain operations across two connections become one transaction,
or redesign the existing optimistic undo timeline. A process already holding a
poisoned transaction needs a normal restart; no deletion of DB/WAL/SHM files.
