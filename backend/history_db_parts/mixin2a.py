"""HistoryDB mixin2a (<150)."""
import asyncio, json, logging, re
from typing import Iterable, Optional

class HistoryDBMixin2a:
    async def _rebuild_legacy_messages(self, columns: list[str]) -> None:
        """Rebuild a pre-persons `messages` table into the canonical shape.

        The legacy table is renamed away first (no byte is destroyed), a
        canonical `messages` is created, and every row is copied over —
        attributed to a person derived from the legacy `nick` column when
        there is one. Rows that cannot be attributed stay in the renamed
        table as quarantine and the archive continues empty.
        """
        path = os.path.basename(self.path)
        quarantine = ("messages_legacy_"
                      + datetime.now().strftime("%Y%m%d%H%M%S"))
        have = set(columns)
        # index names are global in SQLite: the legacy table's indexes must
        # go before `CREATE INDEX IF NOT EXISTS` can rebuild them here
        # (auto-indexes from table constraints cannot be dropped — they die
        # with the table itself)
        legacy_indexes = await self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='messages' AND sql IS NOT NULL")
        for (idx_name,) in legacy_indexes:
            try:
                await self._conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
            except Exception as e:                  # noqa: BLE001
                log.warning("cannot drop legacy index %s: %s", idx_name, e)
        await self._conn.execute(f"ALTER TABLE messages RENAME TO {quarantine}")
        await self._conn.execute(TABLE_SQL["messages"])
        total = await self._count_rows(quarantine)
        if "nick" not in have:
            await self._conn.commit()
            log.warning(
                "%s: legacy messages table has no person_id and no nick — "
                "%d row(s) kept untouched in %s, the archive starts empty",
                path, total, quarantine)
            return
        from backend.history_models import dedupe_key  # local: avoid cycles
        rows = await self.db_fetch_legacy(quarantine, columns)
        shared = [col for col, _decl in TABLE_COLUMNS["messages"]
                  if col in have and col != "person_id"]
        person_cache: dict[str, int] = {}
        copied = 0
        for row in rows:
            nick = self.normalise_nick(row.get("nick") or "")
            if not nick:
                nick = "Unknown"
            person_id = person_cache.get(nick)
            if person_id is None:
                person_id = await self._person_for_nick(nick)
                person_cache[nick] = person_id
            values = [row.get(col) for col in shared]
            try:
                cur = await self._conn.execute(
                    f"INSERT INTO messages(person_id, {', '.join(shared)}) "
                    f"VALUES(?, {', '.join('?' for _ in shared)})",
                    [person_id] + values)
                copied += 1
            except Exception as e:                  # noqa: BLE001
                log.warning("cannot copy legacy message row: %s", e)
                continue
            # recompute the identity this row never had (payload = the media
            # url when the row points at media, the text otherwise)
            payload = row.get("text") or ""
            if row.get("media_id"):
                url = await self.fetchone(
                    "SELECT url FROM media WHERE id=?", (row["media_id"],))
                payload = (url[0] if url else "") or payload
            key = dedupe_key(row.get("direction") or "in", nick,
                             row.get("ts_display") or "",
                             row.get("kind") or "text", payload)
            await self._conn.execute(
                "UPDATE messages SET text_lc=?, dup_key=? WHERE id=?",
                (str(row.get("text") or "").lower(), key, cur.lastrowid))
        await self._conn.commit()
        if copied == total:
            # explicit-id inserts leave AUTOINCREMENT behind; drop the stale
            # counter so the next insert continues from max(id) + 1
            await self._conn.execute(
                "DELETE FROM sqlite_sequence WHERE name='messages'")
            await self._conn.execute(f"DROP TABLE {quarantine}")
            await self._conn.commit()
        log.info("%s: rebuilt the legacy messages table — %d/%d row(s) "
                 "attributed to %d person(s)",
                 path, copied, total, len(person_cache))

