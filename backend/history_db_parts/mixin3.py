"""HistoryDB mixin3 migrate (<150)."""
import asyncio, json, logging, re
from typing import Iterable, Optional

class HistoryDBMixin3:
    async def _read_version(self) -> Optional[str]:
        try:
            value = await self.get_meta("schema_version")
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
                f"database {os.path.basename(self.path)} has an incomplete "
                f"schema: {', '.join(problems[:6])}")

    #: columns added after the first release — old files are upgraded in
    #: place. Kept as an alias of the canonical map: every missing column is
    #: now found by comparing against TABLE_COLUMNS (Bug 5, 2026-09-08).
    @property
    def LATE_COLUMNS(self) -> dict:
        return {name: list(cols) for name, cols in TABLE_COLUMNS.items()}

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
        from backend.history_models import dedupe_key  # local: avoid cycles
        rows = await self.fetchall(
            "SELECT m.id, m.person_id, m.direction, m.from_nick, m.kind, "
            "m.text, m.ts_display, COALESCE(md.url, '') AS media_url "
            "FROM messages m LEFT JOIN media md ON md.id = m.media_id "
            "WHERE m.dup_key='' AND m.deleted_at=''")
        for row in rows:
            payload = row[7] or row[5]
            key = dedupe_key(row[2], row[3], row[6], row[4], payload)
            # OR IGNORE: another row may already own this identity (a line
            # that was re-collected while its older copy was hidden)
            await self.execute(
                "UPDATE OR IGNORE messages SET dup_key=? WHERE id=?",
                (key, row[0]))
        if rows:
            await self.commit()

        # keep the earliest id for each (person, dup_key)
        before = int(await self.scalar(
            "SELECT COUNT(*) FROM messages WHERE dup_key<>''", (), 0))
        await self.execute(
            "DELETE FROM messages WHERE dup_key<>'' AND id NOT IN ("
            "SELECT MIN(id) FROM messages WHERE dup_key<>'' "
            "GROUP BY person_id, dup_key)")
        await self.commit()
        deleted = before - int(await self.scalar(
            "SELECT COUNT(*) FROM messages WHERE dup_key<>''", (), 0))

        # resequence ord only when duplicate removal left holes
        if deleted:
            res = await self.fetchall(
                "SELECT person_id, id FROM messages "
                "ORDER BY person_id, day, ts_display, ord, id")
            current = None
            position = 0
            for person_id, mid in res:
                if current != person_id:
                    current = person_id
                    position = 0
                position += 1
                await self.execute("UPDATE messages SET ord=? WHERE id=?",
                                   (position, mid))
            await self.commit()

        # the index must exist even before the first insert (fresh DBs)
        await self.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dup_key "
            "ON messages(person_id, dup_key) WHERE dup_key <> ''")
        await self.commit()

    async def _try_fts(self) -> bool:
        try:
            await self.conn.executescript(FTS_SCHEMA)
            await self.conn.commit()
            return True
        except Exception as e:                      # noqa: BLE001
            log.warning("FTS5 unavailable, falling back to LIKE search: %s", e)
            return False

