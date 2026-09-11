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
    """The writer's turn of ONE connection: begin on the first write."""

    def __init__(self, token, path: str = ""):
        self._token = token
        self._gate = gate_for(path)
        self.held = False

    async def begin(self) -> bool:
        """Hold the turn for this connection (idempotent per transaction)."""
        if self.held:
            return True
        self.held = True
        return await self._gate.enter(self._token)

    def end(self) -> None:
        """The transaction ended: commit, rollback or an empty turn."""
        if not self.held:
            return
        self.held = False
        self._gate.leave(self._token)

    def drop(self) -> None:
        """The connection is unusable (closed, or a statement failed)."""
        self.end()


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
