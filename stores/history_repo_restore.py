"""Restore rows — extracted from PersonLifecycle (H-C4).

One named responsibility: restore ladder (_restore_rows, _restore_one_row).

Design: AREA_C H-C4 — helper named by responsibility, ≤200 LOC.
"""

from __future__ import annotations

from stores.history_models import LineIdentity, dedupe_key


def _hidden_row_key(row: dict) -> str:
    return dedupe_key(
        LineIdentity(
            row.get("direction") or "in",
            row.get("from_nick") or "",
            row.get("ts_display") or "",
            row.get("kind") or "text",
            row.get("media_url") or row.get("text") or "",
        )
    )


def _sig_or(current: dict, key: str, value):
    return current.get(key, "") if value is None else value


class RestoreLadder:
    def __init__(self, owner):
        self._owner = owner

    async def _restore_rows(self, person_id: int, token: str) -> int:
        rows = await self._owner.db.fetchdicts(
            "SELECT m.id, m.direction, m.from_nick, m.kind, m.text, m.ts_display, md.url AS media_url "
            "FROM messages m LEFT JOIN media md ON md.id = m.media_id WHERE m.person_id=? AND m.deleted_at=?",
            (person_id, token),
        )
        if not rows:
            return 0
        alive = {
            r[0]
            for r in await self._owner.db.fetchall(
                "SELECT dup_key FROM messages WHERE person_id=? AND deleted_at='' AND dup_key<>''", (person_id,)
            )
        }
        restored = 0
        for row in rows:
            if await self._restore_one_row(row, token, alive):
                restored += 1
        await self._owner.db.commit()
        return restored

    async def _restore_one_row(self, row, token: str, alive: set) -> bool:
        key = _hidden_row_key(row)
        if key and key in alive:
            await self._owner.db.execute(
                "DELETE FROM messages WHERE id=? AND deleted_at=?", (int(row["id"]), token)
            )
            return False
        await self._owner.db.execute(
            "UPDATE messages SET deleted_at='', dup_key=? WHERE id=?", (key, int(row["id"]))
        )
        if key:
            alive.add(key)
        return True
