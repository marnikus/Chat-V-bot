"""SQLite-backed user memory: discovery, status tracking, CRUD."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import aiosqlite

log = logging.getLogger("chatbot")

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
    def __init__(self, db_path: str = "chatbot.db"):
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        log.info("UserMemory DB ready: %s", self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def upsert_user(self, user: UserRecord) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        cur = await self._db.execute("SELECT id,messaged FROM users WHERE nick=?", (user.nick,))
        row = await cur.fetchone()
        if row:
            await self._db.execute(
                "UPDATE users SET last_seen=?,gender=?,registered=?,anonymous=?,guest=? WHERE nick=?",
                (now, user.gender, user.registered, user.anonymous, user.guest, user.nick))
            await self._db.commit()
            return "known"
        await self._db.execute(
            "INSERT INTO users(nick,gender,registered,anonymous,guest,first_seen,last_seen,messaged) "
            "VALUES(?,?,?,?,?,?,?,0)",
            (user.nick, user.gender, user.registered, user.anonymous, user.guest, now, now))
        await self._db.commit()
        return "new"

    async def upsert_many(self, users: list[UserRecord]) -> tuple[int, int]:
        new_cnt = known_cnt = 0
        for u in users:
            if await self.upsert_user(u) == "new": new_cnt += 1
            else: known_cnt += 1
        return new_cnt, known_cnt

    async def mark_messaged(self, nick: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        await self._db.execute(
            "UPDATE users SET messaged=1,message_count=message_count+1,last_messaged=? WHERE nick=?",
            (now, nick))
        await self._db.commit()

    async def get_queue(self) -> list[UserRecord]:
        cur = await self._db.execute(
            "SELECT nick,gender,registered,anonymous,guest,first_seen,last_seen,"
            "messaged,message_count,last_messaged,notes FROM users WHERE messaged=0 "
            "ORDER BY first_seen DESC")
        return [self._row(r) for r in await cur.fetchall()]

    async def get_all(self) -> list[UserRecord]:
        cur = await self._db.execute(
            "SELECT nick,gender,registered,anonymous,guest,first_seen,last_seen,"
            "messaged,message_count,last_messaged,notes FROM users ORDER BY first_seen DESC")
        return [self._row(r) for r in await cur.fetchall()]

    async def count_unmessaged(self) -> int:
        """Number of people still awaiting a message (the backlog).

        A single COUNT rather than materialising every row through get_all().
        """
        cur = await self._db.execute(
            "SELECT COUNT(*) FROM users WHERE messaged=0")
        row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def get_stats(self) -> dict:
        cur = await self._db.execute("SELECT COUNT(*) FROM users")
        total = (await cur.fetchone())[0]
        cur = await self._db.execute("SELECT COUNT(*) FROM users WHERE messaged=0")
        queued = (await cur.fetchone())[0]
        return {"total": total, "queued": queued, "done": total - queued}

    async def get_user(self, nick: str) -> Optional[UserRecord]:
        cur = await self._db.execute(
            "SELECT nick,gender,registered,anonymous,guest,first_seen,last_seen,"
            "messaged,message_count,last_messaged,notes FROM users WHERE nick=?",
            (nick,))
        row = await cur.fetchone()
        return self._row(row) if row else None

    async def delete_user(self, nick: str) -> bool:
        """Delete a single user by nick. Returns True when a row was removed."""
        cur = await self._db.execute("DELETE FROM users WHERE nick=?", (nick,))
        await self._db.commit()
        removed = cur.rowcount > 0
        log.info("delete_user(%s) → %s", nick, "removed" if removed else "not found")
        return removed

    async def delete_users(self, nicks: list[str]) -> int:
        """Delete many users in one transaction. Returns the number removed."""
        nicks = [n for n in (nicks or []) if n]
        if not nicks:
            return 0
        total = 0
        # chunk to stay well below SQLite's variable limit
        for i in range(0, len(nicks), 500):
            chunk = nicks[i:i + 500]
            marks = ",".join("?" * len(chunk))
            cur = await self._db.execute(
                f"DELETE FROM users WHERE nick IN ({marks})", chunk)
            total += cur.rowcount
        await self._db.commit()
        log.info("delete_users(%d requested) → %d removed", len(nicks), total)
        return total

    async def set_messaged(self, nick: str, messaged: bool) -> bool:
        """Manually flip a user's messaged flag (per-row Mark done / Undo)."""
        if messaged:
            now = datetime.now().isoformat(timespec="seconds")
            cur = await self._db.execute(
                "UPDATE users SET messaged=1,last_messaged=? WHERE nick=?",
                (now, nick))
        else:
            cur = await self._db.execute(
                "UPDATE users SET messaged=0,last_messaged=NULL WHERE nick=?",
                (nick,))
        await self._db.commit()
        return cur.rowcount > 0

    async def reset_messaged(self) -> int:
        """Mark every user as new again.

        A “New” person must never show a message time: clear last_messaged
        alongside the flag (message_count stays — it is a historical
        counter, exactly like the per-row ↩ Undo).
        """
        cur = await self._db.execute(
            "UPDATE users SET messaged=0,last_messaged=NULL")
        await self._db.commit()
        return cur.rowcount

    async def clear_all(self) -> int:
        cur = await self._db.execute("DELETE FROM users")
        await self._db.commit()
        return cur.rowcount

    async def replace_all(self, rows: list[dict]) -> int:
        """Restore a full snapshot: wipe the table and insert the given rows.

        Used by the global undo/redo system to restore the people list to a
        previously recorded state. Timestamps, message_count and notes are
        preserved verbatim (not re-stamped with CURRENT_TIMESTAMP), so a
        restored person is indistinguishable from the original.
        """
        await self._db.execute("DELETE FROM users")
        count = 0
        for row in rows or []:
            nick = str(row.get("nick", "")).strip()
            if not nick:
                continue
            await self._db.execute(
                "INSERT INTO users(nick,gender,registered,anonymous,guest,"
                "first_seen,last_seen,messaged,message_count,last_messaged,"
                "notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (nick,
                 str(row.get("gender") or "unknown"),
                 1 if row.get("registered") else 0,
                 1 if row.get("anonymous") else 0,
                 1 if row.get("guest") else 0,
                 row.get("first_seen") or "",
                 row.get("last_seen") or "",
                 1 if row.get("messaged") else 0,
                 int(row.get("message_count") or 0),
                 row.get("last_messaged"),
                 str(row.get("notes") or "")))
            count += 1
        await self._db.commit()
        log.info("replace_all → %d rows restored", count)
        return count

    @staticmethod
    def _row(r: tuple) -> UserRecord:
        return UserRecord(nick=r[0], gender=r[1], registered=bool(r[2]),
                          anonymous=bool(r[3]), guest=bool(r[4]),
                          first_seen=r[5] or "", last_seen=r[6] or "",
                          messaged=bool(r[7]), message_count=r[8] or 0,
                          last_messaged=r[9], notes=r[10] or "")
