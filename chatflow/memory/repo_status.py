"""User state transitions: discovery, messaging, cooldown requeue (main thread)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..core.models import UserRow, now_iso
from .db import Database


class StatusRepo:
    def __init__(self, db: Database):
        self._db = db

    def upsert_batch(self, rows: list[UserRow],
                     verdicts: dict[str, tuple[bool, str | None]]) -> dict:
        """Insert newly discovered users, promote NEW -> QUEUED/SKIPPED.

        Existing users keep their status (a MESSAGED user never regresses);
        `last_seen` is always refreshed. Returns stats.
        """
        ts = now_iso()
        inserted = queued = skipped = 0
        existing = {r["nickname"] for r in self._db.query("SELECT nickname FROM users")}
        with self._db.conn:
            for r in rows:
                ok, reason = verdicts.get(r.nickname, (False, "no-rules"))
                cur = self._db.conn.execute(
                    "INSERT INTO users(nickname, gender, registered, status, "
                    "skip_reason, first_seen, last_seen) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(nickname) DO UPDATE SET last_seen=excluded.last_seen, "
                    "gender=CASE WHEN users.gender='UNKNOWN' THEN excluded.gender "
                    "ELSE users.gender END",
                    (r.nickname, r.gender, int(r.registered), "NEW",
                     None, ts, ts))
                if r.nickname not in existing:
                    inserted += 1
            for r in rows:
                ok, reason = verdicts.get(r.nickname, (False, "no-rules"))
                if ok:
                    self._db.conn.execute(
                        "UPDATE users SET status='QUEUED' "
                        "WHERE nickname=? AND status='NEW'", (r.nickname,))
                    queued += 1
                else:
                    self._db.conn.execute(
                        "UPDATE users SET status='SKIPPED', "
                        "skip_reason=COALESCE(skip_reason, ?) "
                        "WHERE nickname=? AND status='NEW'", (reason, r.nickname))
                    skipped += 1
            self._db.conn.commit()
        return {"inserted": inserted, "queued": queued, "skipped": skipped}

    def mark_messaged(self, nickname: str) -> bool:
        cur = self._db.execute(
            "UPDATE users SET status='MESSAGED', messaged_at=?, "
            "message_count=message_count+1 "
            "WHERE nickname=? AND status IN ('QUEUED','NEW')",
            (now_iso(), nickname))
        return cur.rowcount > 0

    def requeue_due(self, cooldown_days: int) -> int:
        """MESSAGED users whose cooldown expired -> QUEUED again."""
        cutoff = (datetime.now(timezone.utc) -
                  timedelta(days=max(int(cooldown_days), 0))).isoformat(timespec="seconds")
        cur = self._db.execute(
            "UPDATE users SET status='QUEUED' "
            "WHERE status='MESSAGED' AND messaged_at IS NOT NULL AND messaged_at<=?",
            (cutoff,))
        return cur.rowcount

    def import_records(self, records: list[dict]) -> int:
        """CSV import: upsert with the status given by the file."""
        ts = now_iso()
        n = 0
        with self._db.conn:
            for d in records:
                nick = (d.get("nickname") or "").strip()
                if not nick:
                    continue
                self._db.conn.execute(
                    "INSERT INTO users(nickname, gender, registered, status, "
                    "first_seen, last_seen, messaged_at, message_count, notes) "
                    "VALUES(?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(nickname) DO UPDATE SET gender=excluded.gender, "
                    "registered=excluded.registered, status=excluded.status, "
                    "last_seen=excluded.last_seen, messaged_at=excluded.messaged_at, "
                    "message_count=excluded.message_count, notes=excluded.notes",
                    (nick, d.get("gender", "UNKNOWN"), int(bool(d.get("registered"))),
                     d.get("status", "NEW"), d.get("first_seen") or ts, ts,
                     d.get("messaged_at"), int(d.get("message_count") or 0),
                     d.get("notes") or ""))
                n += 1
            self._db.conn.commit()
        return n
