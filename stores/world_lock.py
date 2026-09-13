"""One write gate per world file — the missing half of One DB = One World.

The message archive (`stores/history_db.py`) and the People queue
(`stores/user_memory.py`) are two connections onto the SAME `.db`. SQLite
admits one writer per file, and the loser of a race does not merely wait: a
connection that has already read cannot upgrade its snapshot, so it fails at
once with ``database is locked``. That is how a Ctrl+Z could report success
while the person stayed deleted — the exception happened inside a scheduled
task and had nowhere to go (bug 2026-09-11).

The gate below is the missing exclusion: a writer holds its world's gate from
its first write statement until the transaction ends, so the other connection
waits its turn instead of failing.

Three properties matter as much as the exclusion itself:

* **Owned by a connection token.** The archive's writer keys the gate by its
  own connection object, the queue by its store object, so "am I already the
  holder?" is a fact about the world, not about which task happens to be
  running. That also makes the turns re-entrant: a guarded operation
  routinely calls another guarded one (delete person → reset cursors →
  recount), and the second take must not deadlock against the first.
* **Given back on every path.** The holder releases on commit, on rollback,
  when a statement fails, and when the store closes.
* **Fail open.** A turn is waited for at most `WAIT_S` seconds; after that
  the caller continues *without* the gate and says so. A forgotten commit
  must never freeze the queue forever, and the fallback is exactly the
  pre-2026-09-11 behaviour (SQLite reports the conflict itself).

No Qt and no imports from `backend/` or `services/`: this is a leaf store
helper, safe to import from anywhere in `stores/`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Callable

log = logging.getLogger("chatbot")

#: how long a writer waits for the world's turn before continuing inline
WAIT_S = 15.0
#: how long SQLite itself waits for an EXTERNAL holder (Drive, AV, a second
#: instance). This never helps the snapshot-upgrade case, only true conflicts.
BUSY_TIMEOUT_MS = 15000
#: writer key for a `WriteTurn.begin`/`end` that runs outside any asyncio task
_NO_TASK = object()
#: the operations that make a connection a writer for the rest of its turn
_WRITE_HEADS = ("insert", "update", "delete", "replace", "create", "drop",
                "alter", "vacuum", "pragma")


def is_write_sql(sql: str) -> bool:
    """True when this statement can hold the file's write lock."""
    text = " ".join(str(sql or "").split()).lower()
    return text.startswith(_WRITE_HEADS)


def is_locked_error(exc) -> bool:
    """True for SQLite's `database is locked` / `database is busy` family."""
    text = str(exc or "").lower()
    return isinstance(exc, Exception) and (
        "locked" in text or "busy" in text)


def gate_for(path: str) -> "WorldGate":
    """The ONE gate of a world file — every caller of a file shares it."""
    key = os.path.normcase(os.path.realpath(str(path or "")))
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            gate = WorldGate(key)
            _GATES[key] = gate
        return gate


class WorldGate:
    """A single-writer turn for one world file, held by a connection token."""

    def __init__(self, key: str = ""):
        self.key = key
        self._token = None
        self._depth = 0
        self._lock = asyncio.Lock()

    # ── the turn ─────────────────────────────────────────────────
    @property
    def busy(self) -> bool:
        """True while some connection holds the world's writer turn."""
        return self._token is not None

    @property
    def holder(self):
        """The token that holds the turn (None when the world is free)."""
        return self._token

    async def enter(self, token) -> bool:
        """Take the turn for `token`; False when it was taken away by force.

        The same token may enter again (the caller already owns the turn), so
        a guarded operation can call another guarded one freely.
        """
        if self._token is token and token is not None:
            self._depth += 1
            return True
        try:
            await asyncio.wait_for(self._lock.acquire(), WAIT_S)
        except asyncio.TimeoutError:
            log.warning("world %s is still busy after %.0fs — writing anyway",
                        self.key, WAIT_S)
            return False
        self._token, self._depth = token, 1
        return True

    def leave(self, token) -> None:
        """Give the turn back; a different token's `leave` is ignored."""
        if self._token is not token or self._depth <= 0:
            return
        self._depth -= 1
        if self._depth:
            return
        self._token = None
        try:
            self._lock.release()
        except RuntimeError:
            # only reachable if a release happened without an acquire — a
            # defensive path, never taken by the callers above
            log.debug("world %s released an unlocked gate",  # pragma: no cover
                      self.key)


class WriteTurn:
    """The writer's turn of ONE connection: begin on the first write.

    One connection can carry overlapping write transactions from several
    asyncio tasks — a collector append beside a UI edit, say. The turn is
    therefore the SET of writer tasks, and the world gate is held for their
    UNION: taken on the first writer's begin, given back only when the last
    one ends. A single ``held`` flag desynchronised the turn from the gate's
    depth the moment two writers overlapped — the first commit cleared the
    flag, the second re-entered, and the turn could stay held by a closed
    connection, after which every writer on that world waited ``WAIT_S`` and
    failed OPEN (bug 2026-09-11's class, caught live in 2026-09-13's
    world-switch flake). Fixed as Round F's residual risk F3c:
    docs/archive/2026-09-13-round-g-write-gate/ROUND_G_DESIGN_2026-09-13.md §5.
    """

    def __init__(self, token, path: str = ""):
        self._token = token
        self._gate = gate_for(path)
        self._writers: set = set()

    @property
    def held(self) -> bool:
        """True while any write transaction is open on this connection."""
        return bool(self._writers)

    async def begin(self) -> bool:
        """Hold the turn for this transaction (idempotent per task).

        `stores/history_db.py` calls this before EVERY write statement, so a
        task already in `_writers` is on its transaction's next statement, not
        starting a new one — SQLite commits are connection-wide, so one task
        cannot have two open transactions on one connection anyway.
        """
        key = asyncio.current_task() or _NO_TASK
        if key in self._writers:
            return True
        self._writers.add(key)
        if len(self._writers) > 1:
            return True     # the gate is already held for this connection
        return await self._gate.enter(self._token)

    def end(self) -> None:
        """This task's transaction ended: commit, rollback or an empty turn.

        An `end` from a task that never wrote is a no-op — releasing another
        task's open transaction was the desync this class exists to prevent.
        """
        key = asyncio.current_task() or _NO_TASK
        if key not in self._writers:
            return
        self._writers.discard(key)
        if self._writers:
            return          # another transaction on this connection is open
        self._gate.leave(self._token)

    def drop(self) -> None:
        """The connection is unusable (closed, or a statement failed).

        Abandons EVERY writer's turn, as the old single-flag `end` did: both
        callers mean "nothing more will commit on this connection", and a
        per-task drop would leave the gate held by a dead one.
        """
        if not self._writers:
            return
        self._writers.clear()
        self._gate.leave(self._token)


@asynccontextmanager
async def world_write(path: str, token=None):
    """Hold a world's writer turn for a whole transaction.

    `token` defaults to the running task, so two `world_write` blocks in one
    task are the same writer and never deadlock each other.
    """
    gate = gate_for(path)
    token = token if token is not None else asyncio.current_task()
    held = await gate.enter(token)
    try:
        yield held
    finally:
        if held:
            gate.leave(token)


async def _rollback(conn) -> None:
    """Best effort: the error that caused the rollback is the one to report."""
    try:
        await conn.rollback()
    except Exception:                                   # noqa: BLE001
        pass


@asynccontextmanager
async def world_transaction(path: str, conn):
    """One writer turn = ONE transaction: commit on exit, rollback on error.

    The call site says what to write; committing and giving the turn back are
    the context manager's job, so a write site can forget neither. An early
    `return` inside the block commits as well — the all-or-nothing semantics
    `replace_all` used to spell out by hand.
    """
    async with world_write(path, conn):
        try:
            yield
        except Exception:                                   # noqa: BLE001
            await _rollback(conn)
            raise
        else:
            await conn.commit()


async def retry_locked(work: Callable, attempts: int = 4, delay: float = 0.3):
    """Call `work()` again while the file is locked by something outside.

    `work` must be re-callable (a coroutine function or a `functools.partial`):
    a retry re-runs the whole operation, and every archive operation is
    idempotent, so re-running it is safe and produces the same final state.
    Errors that are not lock errors are passed straight through.
    """
    for attempt in range(max(1, attempts)):
        try:
            return await work()
        except Exception as exc:                            # noqa: BLE001
            if not is_locked_error(exc) or attempt == attempts - 1:
                raise
            log.warning("world is locked (%s) — retry %d/%d in %.2fs",
                        exc, attempt + 1, attempts - 1, delay * (attempt + 1))
            await asyncio.sleep(delay * (attempt + 1))
    return None                                             # pragma: no cover


async def apply_busy_timeout(conn, path: str = "") -> None:
    """Let SQLite wait for an EXTERNAL writer instead of failing at once.

    This is a courtesy for holders outside the process (Drive sync, an
    antivirus, a second instance). It is NOT the fix for two connections in
    this program — that is the gate above.
    """
    try:
        await conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        await conn.commit()
    except Exception as exc:                                # noqa: BLE001
        log.debug("busy_timeout on %s failed: %s", path or "?", exc)


#: one gate per world file — the process-wide truth about who is writing
_GATES: dict = {}
_GATES_LOCK = threading.Lock()
