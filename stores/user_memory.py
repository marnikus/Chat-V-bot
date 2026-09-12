"""SQLite-backed user memory: discovery, status tracking, CRUD.

The queue is a second connection onto the world file the archive owns (One DB
= One World), so every write here runs inside `world_write()` — the file's
shared writer turn (stores/world_lock.py). Without it the two connections
overlap, and SQLite answers the loser with “database is locked”.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import aiosqlite

from stores.world_lock import apply_busy_timeout, world_transaction

log = logging.getLogger("chatbot")


async def _connect(path: str):
    """Open the queue's connection with the external-holder courtesy set."""
    conn = await aiosqlite.connect(path)
    await apply_busy_timeout(conn, path)
    return conn


_SCHEMA = """CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nick TEXT UNIQUE NOT NULL,
    gender TEXT DEFAULT 'unknown', registered BOOLEAN DEFAULT 0,
    anonymous BOOLEAN DEFAULT 0, guest BOOLEAN DEFAULT 0,
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    messaged BOOLEAN DEFAULT 0, message_count INTEGER DEFAULT 0,
    last_messaged DATETIME, notes TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_users_nick ON users(nick);
CREATE INDEX IF NOT EXISTS idx_users_messaged ON users(messaged);"""


def _as_flag(value) -> int:
    """A snapshot boolean as the 0/1 the column stores."""
    return 1 if value else 0


def _replacement_params(row: dict) -> tuple | None:
    """One snapshot row as the INSERT tuple; None when it has no nick.

    Kept beside `replace_all` rather than inside it so the restore loop reads
    as "coerce, insert, count" — and so a row without a nick is rejected by
    one guard instead of by the UNIQUE constraint half-way through a batch.
    """
    nick = str(row.get("nick", "")).strip()
    if not nick:
        return None
    return (nick,
            str(row.get("gender") or "unknown"),
            _as_flag(row.get("registered")),
            _as_flag(row.get("anonymous")),
            _as_flag(row.get("guest")),
            row.get("first_seen") or "",
            row.get("last_seen") or "",
            _as_flag(row.get("messaged")),
            int(row.get("message_count") or 0),
            row.get("last_messaged"),
            str(row.get("notes") or ""))


@dataclass
class UserRecord:
    nick: str
    gender: str = "unknown"
    registered: bool = False
    anonymous: bool = False
    guest: bool = False
    first_seen: str = ""
    last_seen: str = ""
    messaged: bool = False
    message_count: int = 0
    last_messaged: Optional[str] = None
    notes: str = ""
    status: str = "new"


class UserMemory:
    """The People table: discovery, status tracking, CRUD.

    The reads are delegated to `UserQuery` (B2 split, design §2.6); the name
    `UserMemory` stays the single entry point every caller uses, and the row
    → `UserRecord` conversion stays here because `UserRecord` is this module's
    value object.
    """

    def __init__(self, db_path: str = "chatbot.db"):
        from stores.user_query import UserQuery   # local: that module's rows
        # are built by this one's `_row`, so importing it at module scope
        # would close a cycle
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self.query = UserQuery(self)

    @property
    def db_path(self) -> str:
        """The file the queue currently lives in (the world file since v6)."""
        return self._db_path

    @property
    def is_open(self) -> bool:
        return self._db is not None

    async def init(self) -> None:
        if self._db is not None:
            await self.close()
        self._db = await _connect(self._db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        log.info("UserMemory DB ready: %s", self._db_path)

    async def switch_db(self, path: str) -> None:
        """Point the queue at another world file (ONE DB = ONE WORLD).

        The `users` table travels with the database it belongs to, so a
        world switch must move this connection too — a queue that kept its
        old file would show world A's people while collecting world B.
        """
        target = str(path or "").strip()
        if not target:
            raise ValueError("no database path given")
        # Connect FIRST: when the target is corrupt the old world stays
        # connected instead of stranding the queue on a broken handle.
        new_db = await _connect(target)
        try:
            await new_db.executescript(_SCHEMA)
            await new_db.commit()
        except Exception:
            try:
                await new_db.close()
            except Exception:                        # noqa: BLE001
                pass
            raise
        if self._db is not None:
            await self._db.close()
            self._db = None
        self._db_path = target
        self._db = new_db
        log.info("UserMemory switched to %s", target)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def upsert_user(self, user: UserRecord) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        async with world_transaction(self._db_path, self._db):
            cur = await self._db.execute("SELECT id,messaged FROM users WHERE nick=?", (user.nick,))
            row = await cur.fetchone()
            if row:
                await self._db.execute(
                    "UPDATE users SET last_seen=?,gender=?,registered=?,anonymous=?,guest=? WHERE nick=?",
                    (now, user.gender, user.registered, user.anonymous, user.guest, user.nick))
                return "known"
            await self._db.execute(
                "INSERT INTO users(nick,gender,registered,anonymous,guest,first_seen,last_seen,messaged) "
                "VALUES(?,?,?,?,?,?,?,0)",
                (user.nick, user.gender, user.registered, user.anonymous, user.guest, now, now))
        return "new"

    async def upsert_many(self, users: list[UserRecord]) -> tuple[int, int]:
        new_cnt = known_cnt = 0
        for u in users:
            if await self.upsert_user(u) == "new": new_cnt += 1
            else: known_cnt += 1
        return new_cnt, known_cnt

    async def mark_messaged(self, nick: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        async with world_transaction(self._db_path, self._db):
            await self._db.execute(
                "UPDATE users SET messaged=1,message_count=message_count+1,last_messaged=? WHERE nick=?",
                (now, nick))

    # ── reads (delegated to UserQuery, which owns the SELECT) ────
    async def get_queue(self) -> list[UserRecord]:
        return await self.query.get_queue()

    async def get_all(self) -> list[UserRecord]:
        return await self.query.get_all()

    async def count_unmessaged(self) -> int:
        return await self.query.count_unmessaged()

    async def get_stats(self) -> dict:
        return await self.query.get_stats()

    async def get_user(self, nick: str) -> Optional[UserRecord]:
        return await self.query.get_user(nick)

    async def delete_user(self, nick: str) -> bool:
        """Delete a single user by nick. Returns True when a row was removed."""
        async with world_transaction(self._db_path, self._db):
            cur = await self._db.execute("DELETE FROM users WHERE nick=?", (nick,))
        removed = cur.rowcount > 0
        log.info("delete_user(%s) → %s", nick, "removed" if removed else "not found")
        return removed

    async def delete_users(self, nicks: list[str]) -> int:
        """Delete many users in one transaction. Returns the number removed."""
        nicks = [n for n in (nicks or []) if n]
        if not nicks:
            return 0
        total = 0
        async with world_transaction(self._db_path, self._db):
            # chunk to stay well below SQLite's variable limit
            for i in range(0, len(nicks), 500):
                chunk = nicks[i:i + 500]
                marks = ",".join("?" * len(chunk))
                cur = await self._db.execute(
                    f"DELETE FROM users WHERE nick IN ({marks})", chunk)
                total += cur.rowcount
        log.info("delete_users(%d requested) → %d removed", len(nicks), total)
        return total

    async def set_messaged(self, nick: str, messaged: bool) -> bool:
        """Manually flip a user's messaged flag (per-row Mark done / Undo)."""
        async with world_transaction(self._db_path, self._db):
            if messaged:
                now = datetime.now().isoformat(timespec="seconds")
                cur = await self._db.execute(
                    "UPDATE users SET messaged=1,last_messaged=? WHERE nick=?",
                    (now, nick))
            else:
                cur = await self._db.execute(
                    "UPDATE users SET messaged=0,last_messaged=NULL WHERE nick=?",
                    (nick,))
        return cur.rowcount > 0

    async def reset_messaged(self) -> int:
        """Mark every user as new again.

        A “New” person must never show a message time: clear last_messaged
        alongside the flag (message_count stays — it is a historical
        counter, exactly like the per-row ↩ Undo).
        """
        async with world_transaction(self._db_path, self._db):
            cur = await self._db.execute(
                "UPDATE users SET messaged=0,last_messaged=NULL")
        return cur.rowcount

    async def clear_all(self) -> int:
        async with world_transaction(self._db_path, self._db):
            cur = await self._db.execute("DELETE FROM users")
        return cur.rowcount

    async def replace_all(self, rows: list[dict]) -> int:
        """Restore a full snapshot: wipe the table and insert the given rows.

        Used by the global undo/redo system to restore the people list to a
        previously recorded state. Timestamps, message_count and notes are
        preserved verbatim (not re-stamped with CURRENT_TIMESTAMP), so a
        restored person is indistinguishable from the original. The whole
        restore is ONE transaction: a garbage row can never leave the table
        half-replaced.
        """
        count = 0
        async with world_transaction(self._db_path, self._db):
            await self._db.execute("DELETE FROM users")
            for row in rows or []:
                params = _replacement_params(row)
                if params is None:
                    continue
                await self._db.execute(
                    "INSERT INTO users(nick,gender,registered,anonymous,guest,"
                    "first_seen,last_seen,messaged,message_count,last_messaged,"
                    "notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)", params)
                count += 1
        log.info("replace_all → %d rows restored", count)
        return count

    @staticmethod
    def _row(r: tuple) -> UserRecord:
        return UserRecord(nick=r[0], gender=r[1], registered=bool(r[2]),
                          anonymous=bool(r[3]), guest=bool(r[4]),
                          first_seen=r[5] or "", last_seen=r[6] or "",
                          messaged=bool(r[7]), message_count=r[8] or 0,
                          last_messaged=r[9], notes=r[10] or "")
