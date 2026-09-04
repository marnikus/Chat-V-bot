"""User record queries and simple edits (main thread)."""
from __future__ import annotations

from ..core.models import UserRecord
from .db import Database

_COLUMNS = ("id, nickname, gender, registered, status, skip_reason, "
            "first_seen, last_seen, messaged_at, message_count, notes")


class UserRepo:
    def __init__(self, db: Database):
        self._db = db

    def _records(self, rows) -> list[UserRecord]:
        return [UserRecord.from_row(r) for r in rows]

    def counts(self) -> dict:
        row = self._db.query(
            "SELECT COUNT(*) total, "
            "SUM(status='NEW') new, SUM(status='QUEUED') queued, "
            "SUM(status='MESSAGED') messaged, SUM(status='SKIPPED') skipped "
            "FROM users")[0]
        return {k: int(row[k] or 0) for k in
                ("total", "new", "queued", "messaged", "skipped")}

    def list(self, status: str | None = None, limit: int = 200,
             offset: int = 0, order: str = "recent") -> list[UserRecord]:
        order_sql = {"recent": "last_seen DESC, id DESC",
                     "oldest": "last_seen ASC, id ASC",
                     "name": "nickname COLLATE NOCASE ASC"}.get(order, "last_seen DESC")
        sql = f"SELECT {_COLUMNS} FROM users"
        params: list = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += f" ORDER BY {order_sql} LIMIT ? OFFSET ?"
        params += [max(int(limit), 1), max(int(offset), 0)]
        return self._records(self._db.query(sql, tuple(params)))

    def all_records(self) -> list[UserRecord]:
        return self._records(self._db.query(f"SELECT {_COLUMNS} FROM users ORDER BY id"))

    def get(self, nickname: str) -> UserRecord | None:
        rows = self._db.query(f"SELECT {_COLUMNS} FROM users WHERE nickname=?", (nickname,))
        return self._records(rows)[0] if rows else None

    def get_by_id(self, user_id: int) -> UserRecord | None:
        rows = self._db.query(f"SELECT {_COLUMNS} FROM users WHERE id=?", (int(user_id),))
        return self._records(rows)[0] if rows else None

    def queued_nicks(self, order: str = "top") -> list[str]:
        tail = "last_seen ASC, id ASC" if order == "top" else "RANDOM()"
        rows = self._db.query(
            f"SELECT nickname FROM users WHERE status='QUEUED' ORDER BY {tail}")
        return [r["nickname"] for r in rows]

    def set_status(self, user_id: int, status: str, reason: str | None = None) -> bool:
        cur = self._db.execute(
            "UPDATE users SET status=?, skip_reason=? WHERE id=?",
            (status, reason, int(user_id)))
        return cur.rowcount > 0

    def set_notes(self, user_id: int, notes: str) -> bool:
        cur = self._db.execute("UPDATE users SET notes=? WHERE id=?", (notes, int(user_id)))
        return cur.rowcount > 0

    def delete(self, user_id: int) -> bool:
        cur = self._db.execute("DELETE FROM users WHERE id=?", (int(user_id),))
        return cur.rowcount > 0

    def reset_all(self, status: str = "NEW") -> int:
        cur = self._db.execute(
            "UPDATE users SET status=?, skip_reason=NULL WHERE status IN ('NEW','QUEUED','SKIPPED')",
            (status,))
        return cur.rowcount
