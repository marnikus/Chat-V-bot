"""Legacy rebuild — extracted from SchemaMigrator (H-C4).

One named responsibility: rebuilding a pre-persons `messages` table and
dropping the legacy UNIQUE(person_id, fp, day) constraint. Keeps the
phase orchestration in SchemaMigrator, moves the ladder here.

Design: AREA_C H-C4 — helper named by responsibility, ≤200 LOC.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from stores.history_schema import LEGACY_MESSAGES_CONSTRAINT, TABLE_COLUMNS, TABLE_SQL

log = logging.getLogger("chatbot")


class LegacyRebuild:
    def __init__(self, owner):
        self._owner = owner

    async def _drop_legacy_indexes(self) -> None:
        legacy = await self._owner.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='messages' AND sql IS NOT NULL"
        )
        for (idx_name,) in legacy:
            try:
                await self._owner._conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
            except Exception as exc:  # noqa: BLE001
                log.warning("cannot drop legacy index %s: %s", idx_name, exc)

    async def _count_rows(self, table: str) -> int:
        try:
            row = await self._owner.fetchone(f"SELECT COUNT(*) FROM {table}")
            return int(row[0]) if row else 0
        except Exception:  # noqa: BLE001
            return 0

    async def _person_for_nick(self, nick: str) -> int:
        row = await self._owner.fetchone("SELECT id FROM persons WHERE nick=?", (nick,))
        if row:
            return int(row[0])
        stamp = datetime.now().isoformat(timespec="seconds")
        cur = await self._owner._conn.execute(
            "INSERT INTO persons(nick, nick_lc, first_seen, last_seen, created_at) VALUES(?,?,?,?,?)",
            (nick, nick.lower(), stamp, stamp, stamp),
        )
        return int(cur.lastrowid)

    async def _person_id_for(self, nick: str, cache: dict) -> int:
        pid = cache.get(nick)
        if pid is None:
            pid = await self._person_for_nick(nick)
            cache[nick] = pid
        return pid

    async def _copy_one_legacy(self, row: dict, shared: list, person_id: int, nick: str) -> bool:
        values = [row.get(col) for col in shared]
        try:
            cur = await self._owner._conn.execute(
                f"INSERT INTO messages(person_id, {', '.join(shared)}) VALUES(?, {', '.join('?' for _ in shared)})",
                [person_id] + values,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("cannot copy legacy message row: %s", exc)
            return False
        await self._stamp_legacy_identity(cur.lastrowid, row, nick)
        return True

    async def _stamp_legacy_identity(self, row_id, row: dict, nick: str) -> None:
        from stores.history_models import LineIdentity, dedupe_key

        payload = row.get("text") or ""
        if row.get("media_id"):
            url = await self._owner.fetchone("SELECT url FROM media WHERE id=?", (row["media_id"],))
            payload = (url[0] if url else "") or payload
        key = dedupe_key(
            LineIdentity(row.get("direction") or "in", nick, row.get("ts_display") or "", row.get("kind") or "text", payload)
        )
        await self._owner._conn.execute(
            "UPDATE messages SET text_lc=?, dup_key=? WHERE id=?",
            (str(row.get("text") or "").lower(), key, row_id),
        )

    async def _copy_legacy_rows(self, quarantine: str, columns: list, have: set) -> tuple:
        rows = await self.db_fetch_legacy(quarantine, columns)
        shared = [col for col, _ in TABLE_COLUMNS["messages"] if col in have and col != "person_id"]
        cache: dict[str, int] = {}
        copied = 0
        for row in rows:
            nick = (self._owner.normalise_nick(row.get("nick") or "") or "Unknown")
            pid = await self._person_id_for(nick, cache)
            if await self._copy_one_legacy(row, shared, pid, nick):
                copied += 1
        return copied, len(cache)

    async def db_fetch_legacy(self, table: str, columns: list[str]) -> list[dict]:
        wanted = [col for col, _ in TABLE_COLUMNS["messages"] if col in set(columns)]
        wanted += [c for c in ("nick",) if c in set(columns) and c not in wanted]
        return await self._owner.fetchdicts(f"SELECT {', '.join(wanted)} FROM {table}")

    async def _finish_legacy_rebuild(self, quarantine: str, copied: int, total: int, people: int) -> None:
        if copied != total:
            return
        await self._owner._conn.execute("DELETE FROM sqlite_sequence WHERE name='messages'")
        await self._owner._conn.execute(f"DROP TABLE {quarantine}")
        await self._owner._conn.commit()

    async def _rebuild_legacy_messages(self, columns: list[str]) -> None:
        path = os.path.basename(self._owner.path)
        quarantine = "messages_legacy_" + datetime.now().strftime("%Y%m%d%H%M%S")
        have = set(columns)
        await self._drop_legacy_indexes()
        await self._owner._conn.execute(f"ALTER TABLE messages RENAME TO {quarantine}")
        await self._owner._conn.execute(TABLE_SQL["messages"])
        total = await self._count_rows(quarantine)
        if "nick" not in have:
            await self._owner._conn.commit()
            log.warning(
                "%s: legacy messages table has no person_id and no nick — %d row(s) kept untouched in %s, the archive starts empty",
                path,
                total,
                quarantine,
            )
            return
        copied, people = await self._copy_legacy_rows(quarantine, columns, have)
        await self._owner._conn.commit()
        await self._finish_legacy_rebuild(quarantine, copied, total, people)
        log.info(
            "%s: rebuilt the legacy messages table — %d/%d row(s) attributed to %d person(s)",
            path,
            copied,
            total,
            people,
        )

    async def _has_legacy_messages_constraint(self) -> bool:
        row = await self._owner.fetchone("SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'")
        sql = str(row[0] or "").upper().replace(" ", "") if row else ""
        return LEGACY_MESSAGES_CONSTRAINT.upper().replace(" ", "") in sql

    async def _rebuild_messages_constraint(self) -> None:
        path = os.path.basename(self._owner.path)
        quarantine = "messages_old_" + datetime.now().strftime("%Y%m%d%H%M%S")
        legacy = await self._owner.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='messages' AND sql IS NOT NULL"
        )
        for (idx_name,) in legacy:
            try:
                await self._owner._conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
            except Exception as exc:  # noqa: BLE001
                log.warning("cannot drop index %s before rebuild: %s", idx_name, exc)
        await self._owner._conn.execute(f"ALTER TABLE messages RENAME TO {quarantine}")
        await self._owner._conn.execute(TABLE_SQL["messages"])
        cur = await self._owner._conn.execute(f"PRAGMA table_info({quarantine})")
        old_cols = [row[1] for row in await cur.fetchall()]
        await cur.close()
        canonical = [col for col, _ in TABLE_COLUMNS["messages"]]
        shared = [col for col in canonical if col in set(old_cols)]
        await self._owner._conn.execute(
            f"INSERT INTO messages({', '.join(shared)}) SELECT {', '.join(shared)} FROM {quarantine}"
        )
        total = await self._count_rows(quarantine)
        await self._owner._conn.execute("DELETE FROM sqlite_sequence WHERE name='messages'")
        await self._owner._conn.commit()
        await self._owner._conn.execute(f"DROP TABLE {quarantine}")
        await self._owner._conn.commit()
        log.info(
            "%s: rebuilt the messages table without the legacy UNIQUE(person_id, fp, day) constraint — %d row(s) kept",
            path,
            total,
        )
