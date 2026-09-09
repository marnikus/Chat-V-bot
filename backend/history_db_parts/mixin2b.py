"""HistoryDB mixin2b (<150)."""
import asyncio, json, logging, re
from typing import Iterable, Optional

class HistoryDBMixin2b:
    async def _has_legacy_messages_constraint(self) -> bool:
        """Does this file's `messages` still carry UNIQUE(person_id, fp, day)?

        That constraint made a cleared conversation un-collectable: every
        re-collected line collided with its hidden twin and INSERT OR IGNORE
        dropped it silently ("Added 25" next to "In archive 0", Bugs 3 & 4
        of 2026-09-08). Deduping moved to the partial unique index on
        (person_id, dup_key) in v4; the table constraint is redundant since.
        """
        row = await self.fetchone(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='messages'")
        sql = str(row[0] or "").upper().replace(" ", "") if row else ""
        return LEGACY_MESSAGES_CONSTRAINT.upper().replace(" ", "") in sql

    async def _rebuild_messages_constraint(self) -> None:
        """One-time rebuild that drops the legacy UNIQUE(person_id, fp, day).

        Every row is copied as-is (person_id included) — this only changes
        the table shape, never the data.
        """
        path = os.path.basename(self.path)
        quarantine = ("messages_old_"
                      + datetime.now().strftime("%Y%m%d%H%M%S"))
        legacy_indexes = await self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='messages' AND sql IS NOT NULL")
        for (idx_name,) in legacy_indexes:
            try:
                await self._conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
            except Exception as e:                  # noqa: BLE001
                log.warning("cannot drop index %s before rebuild: %s",
                            idx_name, e)
        await self._conn.execute(f"ALTER TABLE messages RENAME TO {quarantine}")
        await self._conn.execute(TABLE_SQL["messages"])
        # copy the columns the old table actually has (an older file may be
        # missing late columns — they take their defaults), person_id included
        cur = await self._conn.execute(f"PRAGMA table_info({quarantine})")
        old_columns = [row[1] for row in await cur.fetchall()]
        await cur.close()
        canonical = [col for col, _ in TABLE_COLUMNS["messages"]]
        shared = [col for col in canonical if col in set(old_columns)]
        await self._conn.execute(
            f"INSERT INTO messages({', '.join(shared)}) "
            f"SELECT {', '.join(shared)} FROM {quarantine}")
        total = await self._count_rows(quarantine)
        await self._conn.execute(
            "DELETE FROM sqlite_sequence WHERE name='messages'")
        await self._conn.commit()
        await self._conn.execute(f"DROP TABLE {quarantine}")
        await self._conn.commit()
        log.info("%s: rebuilt the messages table without the legacy "
                 "UNIQUE(person_id, fp, day) constraint — %d row(s) kept",
                 path, total)

    async def _person_for_nick(self, nick: str) -> int:
        """The archive person for a nick, created when missing (repair path)."""
        row = await self.fetchone("SELECT id FROM persons WHERE nick=?",
                                  (nick,))
        if row:
            return int(row[0])
        stamp = datetime.now().isoformat(timespec="seconds")
        cur = await self._conn.execute(
            "INSERT INTO persons(nick, nick_lc, first_seen, last_seen, "
            "created_at) VALUES(?,?,?,?,?)",
            (nick, nick.lower(), stamp, stamp, stamp))
        return int(cur.lastrowid)

    @staticmethod
    def normalise_nick(nick: str) -> str:
        return " ".join(str(nick or "").split()).strip()

    async def _count_rows(self, table: str) -> int:
        try:
            row = await self.fetchone(f"SELECT COUNT(*) FROM {table}")
            return int(row[0]) if row else 0
        except Exception:                            # noqa: BLE001
            return 0

    async def db_fetch_legacy(self, table: str, columns: list[str]) -> list[dict]:
        wanted = [col for col, _ in TABLE_COLUMNS["messages"]
                  if col in set(columns)]
        wanted += [c for c in ("nick",) if c in set(columns) and
                   c not in wanted]
        rows = await self.fetchdicts(
            f"SELECT {', '.join(wanted)} FROM {table}")
        return rows

