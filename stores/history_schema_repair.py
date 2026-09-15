"""SchemaMigrator — bringing an existing archive file up to today's schema.

Extracted from `stores/history_db.py` by the AREA B2 split (design §2.4). The
database class owns a connection; this module owns the eleven steps that run
before that connection is handed out: repair the tables, rebuild a pre-v5
`messages`, validate the columns, backfill the dedupe identities, try the FTS
mirror. Splitting them out is what takes `history_db.py` from 605 SLOC to a
file about connections.

The collaborator keeps no state of its own: it reads the connection and the
path off the aggregate at call time (`self._owner`), so `HistoryDB.init()` —
and the tests that swap `db._repair_tables` on the instance — keep working
through the facade.
"""

from __future__ import annotations

import logging

import os
from datetime import datetime
from typing import Optional

from stores.history_schema import (
    FTS_SCHEMA,
    LEGACY_MESSAGES_CONSTRAINT,
    SCHEMA_VERSION,
    TABLE_COLUMNS,
    TABLE_ORDER,
    TABLE_SQL,
)

log = logging.getLogger("chatbot")

from stores.history_schema_legacy import (LegacyConstraintMixin,
                                               LegacyCopyMixin)


class SchemaMigrator(LegacyCopyMixin, LegacyConstraintMixin):
    """Bring an existing archive file up to today's schema."""

    def __init__(self, owner) -> None:
        self._owner = owner

    async def _table_columns(self, table: str) -> Optional[list[str]]:
        """Live column names of `table`, or None when it does not exist."""
        cur = await self._owner._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        cur = await self._owner._conn.execute(f"PRAGMA table_info({table})")
        names = [row[1] for row in await cur.fetchall()]
        await cur.close()
        return names

    async def _repair_tables(self) -> None:
        """Bring every table to the canonical shape before anything reads it.

        Missing tables are created; existing ones are compared column by
        column and widened in place. A `messages` table from before the
        persons model (no `person_id`) is rebuilt with its rows attributed
        to persons — the open must never fail with "no such column:
        person_id" and never leave the file broken for the next connect.
        """
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
            log.info("%s: schema repaired (v%s)",
                     os.path.basename(self._owner.path), SCHEMA_VERSION)

    async def _realign_table(self, name: str,
                             columns: list[str]) -> bool | None:
        """The structural rebuilds a table may need.

        True when one ran, None when the table needs no rebuild — so the
        caller falls through to plain column widening. Only `messages` can
        need a rebuild: it is the table that predates the persons model.
        """
        if name == "messages" and "person_id" not in columns:
            await self._rebuild_legacy_messages(columns)
            return True
        if name == "messages" and \
                await self._has_legacy_messages_constraint():
            await self._rebuild_messages_constraint()
            return True
        return None

    async def _widen_table(self, name: str, columns: list[str]) -> bool:
        """Add the missing columns of one existing table; True when widened.

        A column that cannot be added is logged and skipped, not raised: one
        unwritable column must not stop the rest of the schema from coming
        up, and must not fail the open.
        """
        have = set(columns)
        missing = [(col, decl) for col, decl in TABLE_COLUMNS[name]
                   if col not in have]
        repaired = False
        for col, decl in missing:
            try:
                await self._owner._conn.execute(
                    f"ALTER TABLE {name} ADD COLUMN {col} {decl}")
                log.info("%s: added missing column %s.%s",
                         os.path.basename(self._owner.path), name, col)
                repaired = True
            except Exception as e:                  # noqa: BLE001
                log.warning("cannot add %s.%s: %s", name, col, e)
        return repaired

    async def _count_rows(self, table: str) -> int:
        try:
            row = await self._owner.fetchone(f"SELECT COUNT(*) FROM {table}")
            return int(row[0]) if row else 0
        except Exception:                            # noqa: BLE001
            return 0

    async def db_fetch_legacy(self, table: str, columns: list[str]) -> list[dict]:
        wanted = [col for col, _ in TABLE_COLUMNS["messages"]
                  if col in set(columns)]
        wanted += [c for c in ("nick",) if c in set(columns) and
                   c not in wanted]
        rows = await self._owner.fetchdicts(
            f"SELECT {', '.join(wanted)} FROM {table}")
        return rows

    async def _read_version(self) -> Optional[str]:
        try:
            value = await self._owner.get_meta("schema_version")
            return str(value) if value else None
        except Exception:                            # noqa: BLE001
            return None

    async def _verify_schema(self) -> None:
        """Post-open guarantee: every canonical column really exists.

        Raises one clear error instead of letting every later query fail
        with "no such column: …" (Bug 1, 2026-09-08).
        """
        problems = []
        for name in TABLE_ORDER:
            columns = await self._table_columns(name)
            if columns is None:
                problems.append(f"{name}: table missing")
                continue
            have = set(columns)
            for col, _decl in TABLE_COLUMNS[name]:
                if col not in have:
                    problems.append(f"{name}.{col} missing")
        if problems:
            raise RuntimeError(
                f"database {os.path.basename(self._owner.path)} has an incomplete "
                f"schema: {', '.join(problems[:6])}")

    async def _add_missing_columns(self) -> None:
        """Compatibility shim — the work now happens in `_repair_tables`."""
        await self._repair_tables()

    async def _migrate_dup_keys(self) -> None:
        """Compute `dup_key`, drop pre-existing duplicates and add its index.

        Old databases stored identity as `fingerprint(.., occ) + day`. That is
        why the same physical line was re-inserted when occurrences shifted or
        the day resolution changed. The new key is timestamp + content for the
        person; here we back-fill it for existing rows and keep the earliest
        row for each key, then resequence as a consequence.

        Hidden (soft-deleted) rows whose identity was deliberately released
        by a history clear stay at `dup_key=''` — re-arming them here would
        block the re-collection the clear promised (Bug 3, 2026-09-08).
        """
        await self._backfill_dup_keys()
        if await self._drop_duplicate_rows():
            # resequence ord only when duplicate removal left holes
            await self._resequence_all()
        # the index must exist even before the first insert (fresh DBs)
        await self._owner.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dup_key "
            "ON messages(person_id, dup_key) WHERE dup_key <> ''")
        await self._owner.commit()

    async def _backfill_dup_keys(self) -> None:
        from stores.history_models import LineIdentity, dedupe_key  # local: avoid cycles
        rows = await self._owner.fetchall(
            "SELECT m.id, m.person_id, m.direction, m.from_nick, m.kind, "
            "m.text, m.ts_display, COALESCE(md.url, '') AS media_url "
            "FROM messages m LEFT JOIN media md ON md.id = m.media_id "
            "WHERE m.dup_key='' AND m.deleted_at=''")
        for row in rows:
            payload = row[7] or row[5]
            key = dedupe_key(LineIdentity(row[2], row[3], row[6], row[4],
                                          payload))
            # OR IGNORE: another row may already own this identity (a line
            # that was re-collected while its older copy was hidden)
            await self._owner.execute(
                "UPDATE OR IGNORE messages SET dup_key=? WHERE id=?",
                (key, row[0]))
        if rows:
            await self._owner.commit()

    async def _drop_duplicate_rows(self) -> int:
        """Keep the earliest id for each (person, dup_key)."""
        before = int(await self._owner.scalar(
            "SELECT COUNT(*) FROM messages WHERE dup_key<>''", (), 0))
        await self._owner.execute(
            "DELETE FROM messages WHERE dup_key<>'' AND id NOT IN ("
            "SELECT MIN(id) FROM messages WHERE dup_key<>'' "
            "GROUP BY person_id, dup_key)")
        await self._owner.commit()
        return before - int(await self._owner.scalar(
            "SELECT COUNT(*) FROM messages WHERE dup_key<>''", (), 0))

    async def _resequence_all(self) -> None:
        """Number every person's rows 1..n again, in read order."""
        res = await self._owner.fetchall(
            "SELECT person_id, id FROM messages "
            "ORDER BY person_id, day, ts_display, ord, id")
        current = None
        position = 0
        for person_id, mid in res:
            if current != person_id:
                current = person_id
                position = 0
            position += 1
            await self._owner.execute("UPDATE messages SET ord=? WHERE id=?",
                                      (position, mid))
        await self._owner.commit()

    async def _try_fts(self) -> bool:
        try:
            await self._owner.conn.executescript(FTS_SCHEMA)
            await self._owner.conn.commit()
            return True
        except Exception as e:                      # noqa: BLE001
            log.warning("FTS5 unavailable, falling back to LIKE search: %s", e)
            return False
