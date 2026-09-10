
"""HistoryDB schema migrator — extracted from HistoryDB (AREA B)."""

from __future__ import annotations

import logging
import os
from datetime import datetime

log = logging.getLogger("chatbot")

class SchemaMigrator:
    def __init__(self, db):
        self.db = db

    async def _table_columns(self, table: str):
        cur = await self.db._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        cur = await self.db._conn.execute(f"PRAGMA table_info({table})")
        names = [row[1] for row in await cur.fetchall()]
        await cur.close()
        return names

    async def _repair_tables(self) -> None:
        from stores.history_db import TABLE_COLUMNS, TABLE_SQL, TABLE_ORDER, TABLE_CONSTRAINTS
        repaired = False
        for name in TABLE_ORDER:
            columns = await self._table_columns(name)
            if columns is None:
                await self.db._conn.execute(TABLE_SQL[name])
                continue
            if name == "messages" and "person_id" not in columns:
                await self._rebuild_legacy_messages(columns)
                repaired = True
                continue
            if name == "messages" and await self._has_legacy_messages_constraint():
                await self._rebuild_messages_constraint()
                repaired = True
                continue
            have = set(columns)
            missing = [(col, decl) for col, decl in TABLE_COLUMNS[name] if col not in have]
            for col, decl in missing:
                try:
                    await self.db._conn.execute(f"ALTER TABLE {name} ADD COLUMN {col} {decl}")
                    log.info("%s: added missing column %s.%s", os.path.basename(self.db.path), name, col)
                    repaired = True
                except Exception as e:
                    log.warning("cannot add %s.%s: %s", name, col, e)
        if repaired:
            await self.db._conn.commit()
            from stores.history_db import SCHEMA_VERSION
            log.info("%s: schema repaired (v%s)", os.path.basename(self.db.path), SCHEMA_VERSION)

    async def _rebuild_legacy_messages(self, columns: list[str]) -> None:
        path = os.path.basename(self.db.path)
        quarantine = "messages_legacy_" + datetime.now().strftime("%Y%m%d%H%M%S")
        have = set(columns)
        legacy_indexes = await self.db.fetchall("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='messages' AND sql IS NOT NULL")
        for (idx_name,) in legacy_indexes:
            try:
                await self.db._conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
            except Exception as e:
                log.warning("cannot drop legacy index %s: %s", idx_name, e)
        await self.db._conn.execute(f"ALTER TABLE messages RENAME TO {quarantine}")
        from stores.history_db import TABLE_SQL
        await self.db._conn.execute(TABLE_SQL["messages"])
        total = await self._count_rows(quarantine)
        if "nick" not in have:
            await self.db._conn.commit()
            log.warning("%s: legacy messages table has no person_id and no nick — %d row(s) kept untouched in %s, the archive starts empty", path, total, quarantine)
            return
        from stores.history_models import dedupe_key
        rows = await self.db.db_fetch_legacy(quarantine, columns)
        from stores.history_db import TABLE_COLUMNS
        shared = [col for col, _decl in TABLE_COLUMNS["messages"] if col in have and col != "person_id"]
        person_cache: dict[str, int] = {}
        copied = 0
        for row in rows:
            nick = self.db.normalise_nick(row.get("nick") or "")
            if not nick:
                nick = "Unknown"
            person_id = person_cache.get(nick)
            if person_id is None:
                person_id = await self._person_for_nick(nick)
                person_cache[nick] = person_id
            values = [row.get(col) for col in shared]
            try:
                cur = await self.db._conn.execute(f"INSERT INTO messages(person_id, {', '.join(shared)}) VALUES(?, {', '.join('?' for _ in shared)})", [person_id] + values)
                copied += 1
            except Exception as e:
                log.warning("cannot copy legacy message row: %s", e)
                continue
            payload = row.get("text") or ""
            if row.get("media_id"):
                url = await self.db.fetchone("SELECT url FROM media WHERE id=?", (row["media_id"],))
                payload = (url[0] if url else "") or payload
            key = dedupe_key(row.get("direction") or "in", nick, row.get("ts_display") or "", row.get("kind") or "text", payload)
            await self.db._conn.execute("UPDATE messages SET text_lc=?, dup_key=? WHERE id=?", (str(row.get("text") or "").lower(), key, cur.lastrowid))
        await self.db._conn.commit()
        if copied == total:
            await self.db._conn.execute("DELETE FROM sqlite_sequence WHERE name='messages'")
            await self.db._conn.execute(f"DROP TABLE {quarantine}")
            await self.db._conn.commit()
        log.info("%s: rebuilt the legacy messages table — %d/%d row(s) attributed to %d person(s)", path, copied, total, len(person_cache))

    async def _has_legacy_messages_constraint(self) -> bool:
        from stores.history_db import LEGACY_MESSAGES_CONSTRAINT
        row = await self.db.fetchone("SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'")
        sql = str(row[0] or "").upper().replace(" ", "") if row else ""
        return LEGACY_MESSAGES_CONSTRAINT.upper().replace(" ", "") in sql

    async def _rebuild_messages_constraint(self) -> None:
        path = os.path.basename(self.db.path)
        quarantine = "messages_old_" + datetime.now().strftime("%Y%m%d%H%M%S")
        legacy_indexes = await self.db.fetchall("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='messages' AND sql IS NOT NULL")
        for (idx_name,) in legacy_indexes:
            try:
                await self.db._conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
            except Exception as e:
                log.warning("cannot drop index %s before rebuild: %s", idx_name, e)
        await self.db._conn.execute(f"ALTER TABLE messages RENAME TO {quarantine}")
        from stores.history_db import TABLE_SQL, TABLE_COLUMNS
        await self.db._conn.execute(TABLE_SQL["messages"])
        cur = await self.db._conn.execute(f"PRAGMA table_info({quarantine})")
        old_columns = [row[1] for row in await cur.fetchall()]
        await cur.close()
        canonical = [col for col, _ in TABLE_COLUMNS["messages"]]
        shared = [col for col in canonical if col in set(old_columns)]
        await self.db._conn.execute(f"INSERT INTO messages({', '.join(shared)}) SELECT {', '.join(shared)} FROM {quarantine}")
        total = await self._count_rows(quarantine)
        await self.db._conn.execute("DELETE FROM sqlite_sequence WHERE name='messages'")
        await self.db._conn.commit()
        await self.db._conn.execute(f"DROP TABLE {quarantine}")
        await self.db._conn.commit()
        log.info("%s: rebuilt the messages table without the legacy UNIQUE(person_id, fp, day) constraint — %d row(s) kept", path, total)

    async def _person_for_nick(self, nick: str) -> int:
        row = await self.db.fetchone("SELECT id FROM persons WHERE nick=?", (nick,))
        if row:
            return int(row[0])
        stamp = datetime.now().isoformat(timespec="seconds")
        cur = await self.db._conn.execute("INSERT INTO persons(nick, nick_lc, first_seen, last_seen, created_at) VALUES(?,?,?,?,?)", (nick, nick.lower(), stamp, stamp, stamp))
        return int(cur.lastrowid)

    async def _count_rows(self, table: str) -> int:
        try:
            row = await self.db.fetchone(f"SELECT COUNT(*) FROM {table}")
            return int(row[0]) if row else 0
        except Exception:
            return 0

    async def _migrate_dup_keys(self) -> None:
        from stores.history_models import dedupe_key
        rows = await self.db.fetchall("SELECT m.id, m.person_id, m.direction, m.from_nick, m.kind, m.text, m.ts_display, COALESCE(md.url, '') AS media_url FROM messages m LEFT JOIN media md ON md.id = m.media_id WHERE m.dup_key='' AND m.deleted_at=''")
        for row in rows:
            payload = row[7] or row[5]
            key = dedupe_key(row[2], row[3], row[6], row[4], payload)
            await self.db.execute("UPDATE OR IGNORE messages SET dup_key=? WHERE id=?", (key, row[0]))
        if rows:
            await self.db.commit()
        before = int(await self.db.scalar("SELECT COUNT(*) FROM messages WHERE dup_key<>''", (), 0))
        await self.db.execute("DELETE FROM messages WHERE dup_key<>'' AND id NOT IN (SELECT MIN(id) FROM messages WHERE dup_key<>'' GROUP BY person_id, dup_key)")
        await self.db.commit()
        deleted = before - int(await self.db.scalar("SELECT COUNT(*) FROM messages WHERE dup_key<>''", (), 0))
        if deleted:
            res = await self.db.fetchall("SELECT person_id, id FROM messages ORDER BY person_id, day, ts_display, ord, id")
            current = None
            position = 0
            for person_id, mid in res:
                if current != person_id:
                    current = person_id
                    position = 0
                position += 1
                await self.db.execute("UPDATE messages SET ord=? WHERE id=?", (position, mid))
            await self.db.commit()
        await self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dup_key ON messages(person_id, dup_key) WHERE dup_key <> ''")
        await self.db.commit()
