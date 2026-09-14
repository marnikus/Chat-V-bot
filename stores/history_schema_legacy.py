"""The legacy-`messages` rebuild ladder (Round H step H-C4).

One named concept, ten methods: taking a pre-v5 archive file's `messages`
table — no `CHECK` constraint, no dedupe identity, indexes that today's schema
does not have — and rebuilding it into the current shape without losing a row.
The ladder is quarantine → copy → stamp identity → finish, with the
constraint-only rebuild as the cheaper path when only the `CHECK` is missing.

Split out of `stores/history_schema_repair.py` by the plan's H-C4 rule: a
helper must be named for a responsibility (§16.1.1), and "the legacy rebuild"
is the name the code already used. `SchemaMigrator` keeps the phase
orchestration and the non-legacy repairs; this mixin inherits into it, so
`HistoryDB`'s delegators (`_rebuild_legacy_messages`,
`_has_legacy_messages_constraint`, `_rebuild_messages_constraint`,
`_person_for_nick`) resolve exactly as before.

Import direction: `stores.history_schema` for the schema constants; nothing
imports back.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from stores.history_schema import (
    FTS_SCHEMA,
    LEGACY_MESSAGES_CONSTRAINT,
    SCHEMA_VERSION,
    TABLE_COLUMNS,
    TABLE_ORDER,
    TABLE_SQL,
)

log = logging.getLogger("chatbot")


class LegacyCopyMixin:
    """Quarantine → copy → stamp identity → finish, for a pre-v5 `messages`.

    The rows are the point: nothing is destroyed, every row that can be
    attributed to a person is copied into the canonical table, and the ones
    that cannot stay behind in the renamed quarantine table.
    """

    async def _rebuild_legacy_messages(self, columns: list[str]) -> None:
        """Rebuild a pre-persons `messages` table into the canonical shape.

        The legacy table is renamed away first (no byte is destroyed), a
        canonical `messages` is created, and every row is copied over —
        attributed to a person derived from the legacy `nick` column when
        there is one. Rows that cannot be attributed stay in the renamed
        table as quarantine and the archive continues empty.
        """
        path = os.path.basename(self._owner.path)
        quarantine = ("messages_legacy_"
                      + datetime.now().strftime("%Y%m%d%H%M%S"))
        have = set(columns)
        await self._drop_legacy_indexes()
        await self._owner._conn.execute(
            f"ALTER TABLE messages RENAME TO {quarantine}")
        await self._owner._conn.execute(TABLE_SQL["messages"])
        total = await self._count_rows(quarantine)
        if self._legacy_has_no_identity(have, path, total, quarantine):
            await self._owner._conn.commit()
            return
        copied, people = await self._copy_legacy_rows(quarantine, columns,
                                                      have)
        await self._owner._conn.commit()
        await self._finish_legacy_rebuild(quarantine, copied, total, people)
        log.info("%s: rebuilt the legacy messages table — %d/%d row(s) "
                 "attributed to %d person(s)",
                 path, copied, total, people)

    def _legacy_has_no_identity(self, have: set, path: str, total: int,
                                quarantine: str) -> bool:
        """True when the legacy table has neither person_id nor a nick column.

        Nothing can be attributed then, so the rows stay untouched in the
        quarantine table and the archive starts empty — reported as empty,
        not as a failure (RULE 4).
        """
        if "nick" in have:
            return False
        log.warning(
            "%s: legacy messages table has no person_id and no nick — "
            "%d row(s) kept untouched in %s, the archive starts empty",
            path, total, quarantine)
        return True

    async def _drop_legacy_indexes(self) -> None:
        """Drop the legacy table's own indexes before recreating them here.

        Index names are global in SQLite, so `CREATE INDEX IF NOT EXISTS`
        could not rebuild them while the old ones exist (auto-indexes from
        table constraints cannot be dropped — they die with the table).
        """
        legacy_indexes = await self._owner.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='messages' AND sql IS NOT NULL")
        for (idx_name,) in legacy_indexes:
            try:
                await self._owner._conn.execute(
                    f"DROP INDEX IF EXISTS {idx_name}")
            except Exception as e:                  # noqa: BLE001
                log.warning("cannot drop legacy index %s: %s", idx_name, e)

    async def _copy_legacy_rows(self, quarantine: str, columns: list,
                                have: set) -> tuple:
        """Move every legacy row into the canonical table. Returns
        `(copied, number_of_people)`; a row that cannot be inserted is left
        in the quarantined table."""
        rows = await self.db_fetch_legacy(quarantine, columns)
        shared = [col for col, _decl in TABLE_COLUMNS["messages"]
                  if col in have and col != "person_id"]
        person_cache: dict[str, int] = {}
        copied = 0
        for row in rows:
            nick = (self._owner.normalise_nick(row.get("nick") or "")
                    or "Unknown")
            person_id = await self._person_id_for(nick, person_cache)
            if await self._copy_one_legacy(row, shared, person_id, nick):
                copied += 1
        return copied, len(person_cache)

    async def _person_id_for(self, nick: str, person_cache: dict) -> int:
        """Resolve — and cache — the person behind one legacy nick.

        The cache is the caller's, so a nick is resolved once per rebuild and
        `len(person_cache)` is still the people count even for rows whose
        insert later failed.
        """
        person_id = person_cache.get(nick)
        if person_id is None:
            person_id = await self._person_for_nick(nick)
            person_cache[nick] = person_id
        return person_id

    async def _copy_one_legacy(self, row: dict, shared: list,
                               person_id: int, nick: str) -> bool:
        """Insert one legacy row into the canonical table.

        False means the row stays quarantined: the insert raised and was
        logged, so the rebuild must not count it as copied — and must not
        drop the quarantine table either.
        """
        values = [row.get(col) for col in shared]
        try:
            cur = await self._owner._conn.execute(
                f"INSERT INTO messages(person_id, {', '.join(shared)}) "
                f"VALUES(?, {', '.join('?' for _ in shared)})",
                [person_id] + values)
        except Exception as e:                      # noqa: BLE001
            log.warning("cannot copy legacy message row: %s", e)
            return False
        # recompute the identity this row never had (payload = the media
        # url when the row points at media, the text otherwise)
        await self._stamp_legacy_identity(cur.lastrowid, row, nick)
        return True

    async def _stamp_legacy_identity(self, row_id, row: dict,
                                      nick: str) -> None:
        """The `dup_key` a pre-dedupe row never had, from its own payload."""
        from stores.history_models import LineIdentity, dedupe_key  # local: avoid cycles
        payload = row.get("text") or ""
        if row.get("media_id"):
            url = await self._owner.fetchone(
                "SELECT url FROM media WHERE id=?", (row["media_id"],))
            payload = (url[0] if url else "") or payload
        key = dedupe_key(LineIdentity(row.get("direction") or "in", nick,
                                      row.get("ts_display") or "",
                                      row.get("kind") or "text", payload))
        await self._owner._conn.execute(
            "UPDATE messages SET text_lc=?, dup_key=? WHERE id=?",
            (str(row.get("text") or "").lower(), key, row_id))

    async def _finish_legacy_rebuild(self, quarantine: str, copied: int,
                                     total: int, people: int) -> None:
        """Drop the quarantined table only when every row made it across."""
        if copied != total:
            return
        # explicit-id inserts leave AUTOINCREMENT behind; drop the stale
        # counter so the next insert continues from max(id) + 1
        await self._owner._conn.execute(
            "DELETE FROM sqlite_sequence WHERE name='messages'")
        await self._owner._conn.execute(f"DROP TABLE {quarantine}")
        await self._owner._conn.commit()

    async def _person_for_nick(self, nick: str) -> int:
        """The archive person for a nick, created when missing (repair path)."""
        row = await self._owner.fetchone("SELECT id FROM persons WHERE nick=?",
                                  (nick,))
        if row:
            return int(row[0])
        stamp = datetime.now().isoformat(timespec="seconds")
        cur = await self._owner._conn.execute(
            "INSERT INTO persons(nick, nick_lc, first_seen, last_seen, "
            "created_at) VALUES(?,?,?,?,?)",
            (nick, nick.lower(), stamp, stamp, stamp))
        return int(cur.lastrowid)


class LegacyConstraintMixin:
    """The cheaper path: only the legacy UNIQUE(person_id, fp, day) is wrong.

    The rows are already canonical, so this rebuilds the *table shape* and
    copies every row as-is, person_id included.
    """

    async def _has_legacy_messages_constraint(self) -> bool:
        """Does this file's `messages` still carry UNIQUE(person_id, fp, day)?

        That constraint made a cleared conversation un-collectable: every
        re-collected line collided with its hidden twin and INSERT OR IGNORE
        dropped it silently ("Added 25" next to "In archive 0", Bugs 3 & 4
        of 2026-09-08). Deduping moved to the partial unique index on
        (person_id, dup_key) in v4; the table constraint is redundant since.
        """
        row = await self._owner.fetchone(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='messages'")
        sql = str(row[0] or "").upper().replace(" ", "") if row else ""
        return LEGACY_MESSAGES_CONSTRAINT.upper().replace(" ", "") in sql

    async def _rebuild_messages_constraint(self) -> None:
        """One-time rebuild that drops the legacy UNIQUE(person_id, fp, day).

        Every row is copied as-is (person_id included) — this only changes
        the table shape, never the data.
        """
        path = os.path.basename(self._owner.path)
        quarantine = ("messages_old_"
                      + datetime.now().strftime("%Y%m%d%H%M%S"))
        await self._drop_legacy_indexes()
        await self._owner._conn.execute(f"ALTER TABLE messages RENAME TO {quarantine}")
        await self._owner._conn.execute(TABLE_SQL["messages"])
        await self._copy_shared_columns(quarantine)
        total = await self._count_rows(quarantine)
        await self._owner._conn.execute(
            "DELETE FROM sqlite_sequence WHERE name='messages'")
        await self._owner._conn.commit()
        await self._owner._conn.execute(f"DROP TABLE {quarantine}")
        await self._owner._conn.commit()
        log.info("%s: rebuilt the messages table without the legacy "
                 "UNIQUE(person_id, fp, day) constraint — %d row(s) kept",
                 path, total)

    async def _copy_shared_columns(self, quarantine: str) -> None:
        """Copy the columns the old table actually has, person_id included.

        An older file may be missing late columns — those take their defaults,
        which is why the intersection is computed from `PRAGMA table_info`
        rather than assumed from `TABLE_COLUMNS`.
        """
        cur = await self._owner._conn.execute(f"PRAGMA table_info({quarantine})")
        old_columns = [row[1] for row in await cur.fetchall()]
        await cur.close()
        canonical = [col for col, _ in TABLE_COLUMNS["messages"]]
        shared = [col for col in canonical if col in set(old_columns)]
        await self._owner._conn.execute(
            f"INSERT INTO messages({', '.join(shared)}) "
            f"SELECT {', '.join(shared)} FROM {quarantine}")
