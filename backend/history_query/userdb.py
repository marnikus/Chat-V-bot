"""The Full User Database window and the header/stats read-outs.

`UserDbMixin` owns `list_persons` (the sortable master list), the two stat
read-outs (`db_stats`, `person_stats`) and the `_my_nicks` JSON helper the
paging mixin also reads through the MRO.
"""

from __future__ import annotations

from .person import _day_bounds, _person_item, _stat_int
from .request import PersonPageRequest


class UserDbMixin:
    # ── the user database window ─────────────────────────────────
    @staticmethod
    def _my_nicks(row) -> list:
        import json
        try:
            return json.loads(dict(row).get("my_nicks") or "[]")
        except Exception:                             # noqa: BLE001
            return []

    async def list_persons(self, req: PersonPageRequest) -> dict:
        """One page of the Full User Database, in the order the header asks.

        `req` carries the six options the UI sends as one blob. The response
        echoes the sort key verbatim plus the *resolved* direction, so the UI
        paints the right arrow without duplicating `SORT_COLUMNS` in
        JavaScript.

        The COUNT binds only the `where()` parameters; the page query binds
        `where()` + `order()` + limit/offset, in that order.
        """
        limit = self._clamp(req.limit)
        offset = max(0, int(req.offset or 0))
        where, where_params = req.where()
        order, order_params = req.order()
        total = int(await self.db.scalar(
            f"SELECT COUNT(*) FROM persons WHERE {where}", where_params, 0))
        rows = await self.db.fetchdicts(
            f"SELECT * FROM persons WHERE {where} ORDER BY {order} "
            "LIMIT ? OFFSET ?", where_params + order_params + [limit, offset])
        items = [_person_item(row, self._my_nicks(row)) for row in rows]
        return {"items": items, "total": total,
                "has_more": total > offset + len(items),
                "offset": offset, "limit": limit, "query": req.q,
                "sort": req.sort, "dir": req.resolved_dir()}

    async def db_stats(self) -> dict:
        persons = int(await self.db.scalar(
            "SELECT COUNT(*) FROM persons WHERE deleted_at IS NULL", (), 0))
        return {
            "persons": persons,
            "persons_deleted": int(await self.db.scalar(
                "SELECT COUNT(*) FROM persons WHERE deleted_at IS NOT NULL",
                (), 0)),
            "messages": int(await self.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE deleted_at=''", (), 0)),
            "messages_hidden": int(await self.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE deleted_at<>''", (), 0)),
            # alive messages only — consistent with the `messages` count,
            # so the read-out never mixes hidden (undoable) rows in
            "text_bytes": int(await self.db.scalar(
                "SELECT COALESCE(SUM(LENGTH(text)),0) FROM messages "
                "WHERE deleted_at=''", (), 0)),
            "media": int(await self.db.scalar(
                "SELECT COUNT(*) FROM media", (), 0)),
            "media_cached": int(await self.db.scalar(
                "SELECT COUNT(*) FROM media WHERE state='cached'", (), 0)),
            "media_bytes": int(await self.db.scalar(
                "SELECT SUM(bytes) FROM media WHERE state='cached'", (), 0)),
            "gaps": int(await self.db.scalar("SELECT COUNT(*) FROM gaps",
                                             (), 0)),
            "fts": bool(self.db.fts_enabled),
            "db_bytes": self.db.file_size(),
            "path": self.db.path,
        }

    async def person_stats(self, nick: str) -> dict:
        person = await self._person_row(nick)
        if not person:
            return {"nick": nick, "missing": True, "message_count": 0,
                    "my_nicks": []}
        data = dict(person)
        pid = int(data["id"])
        first_day, last_day, days = await _day_bounds(self.db, pid)
        return {
            "nick": data["nick"],
            "missing": False,
            "message_count": _stat_int(data, "message_count"),
            "messages": _stat_int(data, "message_count"),
            "in_count": _stat_int(data, "in_count"),
            "out_count": _stat_int(data, "out_count"),
            "media_count": _stat_int(data, "media_count"),
            "my_nicks": self._my_nicks(person),
            "first_seen": data.get("first_seen") or "",
            "last_seen": data.get("last_seen") or "",
            "first_day": first_day,
            "last_day": last_day,
            "days": days,
            "hidden": int(await self.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE person_id=? AND "
                "deleted_at<>''", (pid,), 0)),
            "deleted": bool(data.get("deleted_at")),
            "gaps": await self.gaps(pid),
        }
