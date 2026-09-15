"""SchemaMigrator — bringing an existing archive file up to today's schema.

Extracted from `stores/history_db.py` by the AREA B2 split (design §2.4). The
database class owns a connection; this module owns the eleven steps that run
before that connection is handed out: repair the tables, rebuild a pre-v5
`messages`, validate the columns, backfill the dedupe identities, try the FTS
mirror. Splitting them out is what takes `history_db.py` from 605 SLOC to a
file about connections.

H-C4: legacy rebuild ladder moved to `history_schema_legacy.py` (≤200 LOC,
named responsibility). This file keeps phase orchestration.

The collaborator keeps no state of its own: it reads the connection and the
path off the aggregate at call time (`self._owner`), so `HistoryDB.init()` —
and the tests that swap `db._repair_tables` on the instance — keep working
through the facade.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from stores.history_schema import (
    FTS_SCHEMA,
    SCHEMA_VERSION,
    TABLE_COLUMNS,
    TABLE_ORDER,
    TABLE_SQL,
)
from stores.history_schema_legacy import LegacyRebuild

log = logging.getLogger("chatbot")


class SchemaMigrator:
    """Repairs and validates one archive file against `stores.history_schema`."""

    def __init__(self, owner) -> None:
        self._owner = owner
        self._legacy = LegacyRebuild(owner)

    async def _table_columns(self, table: str) -> Optional[list[str]]:
        """Live column names of `table`, or None when it does not exist."""
        cur = await self._owner._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        cur = await self._owner._conn.execute(f"PRAGMA table_info({table})")
        names = [row[1] for row in await cur.fetchall()]
        await cur.close()
        return names

    async def _repair_tables(self) -> None:
        """Bring every table to the canonical shape before anything reads it."""
        repaired = False
        for name in TABLE_ORDER:
            columns = await self._table_columns(name)
            if columns is None:
                await self._owner._conn.execute(TABLE_SQL[name])
                continue
            structural = await self._realign_table(name, columns)
            if structural is not None:
                repaired = repaired or structural
                continue
            repaired = (await self._widen_table(name, columns)) or repaired
        if repaired:
            await self._owner._conn.commit()
            log.info(
                "%s: schema repaired (v%s)",
                os.path.basename(self._owner.path),
                SCHEMA_VERSION,
            )

    async def _realign_table(self, name: str, columns: list[str]) -> bool | None:
        """Structural rebuilds a table may need."""
        if name == "messages" and "person_id" not in columns:
            await self._legacy._rebuild_legacy_messages(columns)
            return True
        if name == "messages" and await self._legacy._has_legacy_messages_constraint():
            await self._legacy._rebuild_messages_constraint()
            return True
        return None

    async def _widen_table(self, name: str, columns: list[str]) -> bool:
        """Add missing columns of one existing table; True when widened."""
        have = set(columns)
        missing = [(col, decl) for col, decl in TABLE_COLUMNS[name] if col not in have]
        repaired = False
        for col, decl in missing:
            try:
                await self._owner._conn.execute(f"ALTER TABLE {name} ADD COLUMN {col} {decl}")
                log.info(
                    "%s: added missing column %s.%s",
                    os.path.basename(self._owner.path),
                    name,
                    col,
                )
                repaired = True
            except Exception as exc:  # noqa: BLE001
                log.warning("cannot add %s.%s: %s", name, col, exc)
        return repaired

    # ── legacy delegates (kept for backward compat, tests patch these) ──
    async def _rebuild_legacy_messages(self, columns: list[str]) -> None:
        return await self._legacy._rebuild_legacy_messages(columns)

    async def _drop_legacy_indexes(self) -> None:
        return await self._legacy._drop_legacy_indexes()

    async def _copy_legacy_rows(self, quarantine: str, columns: list, have: set) -> tuple:
        return await self._legacy._copy_legacy_rows(quarantine, columns, have)

    async def _person_id_for(self, nick: str, person_cache: dict) -> int:
        return await self._legacy._person_id_for(nick, person_cache)

    async def _copy_one_legacy(self, row: dict, shared: list, person_id: int, nick: str) -> bool:
        return await self._legacy._copy_one_legacy(row, shared, person_id, nick)

    async def _stamp_legacy_identity(self, row_id, row: dict, nick: str) -> None:
        return await self._legacy._stamp_legacy_identity(row_id, row, nick)

    async def _finish_legacy_rebuild(self, quarantine: str, copied: int, total: int, people: int) -> None:
        return await self._legacy._finish_legacy_rebuild(quarantine, copied, total, people)

    async def _has_legacy_messages_constraint(self) -> bool:
        return await self._legacy._has_legacy_messages_constraint()

    async def _rebuild_messages_constraint(self) -> None:
        return await self._legacy._rebuild_messages_constraint()

    async def _person_for_nick(self, nick: str) -> int:
        return await self._legacy._person_for_nick(nick)

    async def _count_rows(self, table: str) -> int:
        return await self._legacy._count_rows(table)

    async def db_fetch_legacy(self, table: str, columns: list[str]) -> list[dict]:
        return await self._legacy.db_fetch_legacy(table, columns)

    async def _read_version(self) -> Optional[str]:
        try:
            value = await self._owner.get_meta("schema_version")
            return str(value) if value else None
        except Exception:  # noqa: BLE001
            return None

    async def _verify_schema(self) -> None:
        """Post-open guarantee: every canonical column really exists."""
        problems = []
        for name in TABLE_ORDER:
            columns = await self._table_columns(name)
            if columns is None:
                problems.append(f"{name}: table missing")
                continue
            have = set(columns)
            for col, _ in TABLE_COLUMNS[name]:
                if col not in have:
                    problems.append(f"{name}.{col} missing")
        if problems:
            raise RuntimeError(
                f"database {os.path.basename(self._owner.path)} has an incomplete schema: {', '.join(problems[:6])}"
            )

    async def _add_missing_columns(self) -> None:
        await self._repair_tables()

    async def _migrate_dup_keys(self) -> None:
        await self._backfill_dup_keys()
        if await self._drop_duplicate_rows():
            await self._resequence_all()
        await self._owner.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dup_key ON messages(person_id, dup_key) WHERE dup_key <> ''"
        )
        await self._owner.db.commit() if hasattr(self._owner, 'db') else await self._owner._conn.commit()
        # original used self._owner.execute / commit via HistoryDB wrapper; keep both paths
        try:
            await self._owner.commit()
        except Exception:
            pass

    async def _backfill_dup_keys(self) -> None:
        from stores.history_models import LineIdentity, dedupe_key

        rows = await self._owner.fetchall(
            "SELECT m.id, m.person_id, m.direction, m.from_nick, m.kind, m.text, m.ts_display, COALESCE(md.url, '') AS media_url "
            "FROM messages m LEFT JOIN media md ON md.id = m.media_id WHERE m.dup_key='' AND m.deleted_at=''"
        )
        for row in rows:
            payload = row[7] or row[5]
            key = dedupe_key(LineIdentity(row[2], row[3], row[6], row[4], payload))
            await self._owner.execute("UPDATE OR IGNORE messages SET dup_key=? WHERE id=?", (key, row[0]))
        if rows:
            await self._owner.commit()

    async def _drop_duplicate_rows(self) -> int:
        before = int(await self._owner.scalar("SELECT COUNT(*) FROM messages WHERE dup_key<>''", (), 0))
        await self._owner.execute(
            "DELETE FROM messages WHERE dup_key<>'' AND id NOT IN (SELECT MIN(id) FROM messages WHERE dup_key<>'' GROUP BY person_id, dup_key)"
        )
        await self._owner.commit()
        return before - int(await self._owner.scalar("SELECT COUNT(*) FROM messages WHERE dup_key<>''", (), 0))

    async def _resequence_all(self) -> None:
        res = await self._owner.fetchall(
            "SELECT person_id, id FROM messages ORDER BY person_id, day, ts_display, ord, id"
        )
        current = None
        position = 0
        for person_id, mid in res:
            if current != person_id:
                current = person_id
                position = 0
            position += 1
            await self._owner.execute("UPDATE messages SET ord=? WHERE id=?", (position, mid))
        await self._owner.commit()

    async def _try_fts(self) -> bool:
        try:
            await self._owner.conn.executescript(FTS_SCHEMA)
            await self._owner.conn.commit()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("FTS5 unavailable, falling back to LIKE search: %s", exc)
            return False
