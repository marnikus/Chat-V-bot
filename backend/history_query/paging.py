"""Chronological paging of one conversation.

`PagingMixin` owns the stable page/around readers, the gap list, and the
shared row/limit helpers (`_clamp`, `_person_row`, `_item`) the other mixins
reuse through the MRO.
"""

from __future__ import annotations

from typing import Optional

from .constants import DEFAULT_LIMIT, MAX_LIMIT
from .person import _FIELD_SPECS, _FIELD_SPECS_TAIL, _apply_specs, _item_media


class PagingMixin:
    # ── helpers ──────────────────────────────────────────────────
    @staticmethod
    def _clamp(limit: Optional[int]) -> int:
        try:
            value = int(limit or DEFAULT_LIMIT)
        except (TypeError, ValueError):
            value = DEFAULT_LIMIT
        return max(1, min(MAX_LIMIT, value))

    async def _person_row(self, nick: str):
        return await self.db.fetchone(
            "SELECT * FROM persons WHERE nick=?",
            (" ".join(str(nick or "").split()).strip(),))

    @staticmethod
    def _item(row) -> dict:
        data = dict(row)
        item = _apply_specs(data, _FIELD_SPECS)
        item["media"] = _item_media(data)
        item.update(_apply_specs(data, _FIELD_SPECS_TAIL))
        return item

    # ── paging ───────────────────────────────────────────────────
    async def page(self, nick: str, before_ord: Optional[int] = None,
                   after_ord: Optional[int] = None,
                   limit: int = DEFAULT_LIMIT) -> dict:
        """One screen of a conversation, oldest-first inside the page."""
        limit = self._clamp(limit)
        person = await self._person_row(nick)
        empty = {"nick": nick, "items": [], "has_more": False,
                 "has_newer": False, "total": 0, "gaps": [], "missing": True,
                 "my_nicks": []}
        if not person:
            return empty
        pid = int(person["id"])
        total = int(await self.db.scalar(
            self._COUNT_ALIVE, (pid,), 0))

        if after_ord is not None:
            rows = await self.db.fetchdicts(
                self._SELECT + "WHERE m.person_id=? AND m.deleted_at='' "
                "AND m.ord>? ORDER BY m.ord LIMIT ?",
                (pid, int(after_ord), limit))
        elif before_ord is not None:
            rows = await self.db.fetchdicts(
                self._SELECT + "WHERE m.person_id=? AND m.deleted_at='' "
                "AND m.ord<? ORDER BY m.ord DESC LIMIT ?",
                (pid, int(before_ord), limit))
            rows = list(reversed(rows))
        else:
            rows = await self.db.fetchdicts(
                self._SELECT + "WHERE m.person_id=? AND m.deleted_at='' "
                "ORDER BY m.ord DESC LIMIT ?", (pid, limit))
            rows = list(reversed(rows))

        items = [self._item(r) for r in rows]
        first = items[0]["ord"] if items else 0
        last = items[-1]["ord"] if items else 0
        has_more = bool(await self.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE person_id=? AND "
            "deleted_at='' AND ord<?",
            (pid, first if items else 0), 0)) if items else False
        has_newer = bool(await self.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE person_id=? AND "
            "deleted_at='' AND ord>?",
            (pid, last), 0)) if items else False
        return {
            "nick": person["nick"],
            "items": items,
            "has_more": has_more,
            "has_newer": has_newer,
            "total": total,
            "gaps": await self.gaps(pid),
            "missing": False,
            "my_nicks": self._my_nicks(person),
        }

    async def around(self, nick: str, ord_: int, radius: int = 25) -> dict:
        person = await self._person_row(nick)
        if not person:
            return {"nick": nick, "items": [], "anchor_ord": ord_,
                    "missing": True, "has_more": False, "has_newer": False,
                    "total": 0, "gaps": []}
        pid = int(person["id"])
        rows = await self.db.fetchdicts(
            self._SELECT + "WHERE m.person_id=? AND m.deleted_at='' "
            "AND m.ord BETWEEN ? AND ? "
            "ORDER BY m.ord", (pid, int(ord_) - int(radius),
                               int(ord_) + int(radius)))
        items = [self._item(r) for r in rows]
        return {
            "nick": person["nick"],
            "items": items,
            "anchor_ord": int(ord_),
            "missing": False,
            "total": int(await self.db.scalar(self._COUNT_ALIVE, (pid,), 0)),
            "has_more": bool(items) and items[0]["ord"] > 1,
            "has_newer": bool(await self.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE person_id=? AND "
                "deleted_at='' AND ord>?",
                (pid, items[-1]["ord"] if items else 0), 0)),
            "gaps": await self.gaps(pid),
        }

    async def gaps(self, person_id: int) -> list[dict]:
        rows = await self.db.fetchdicts(
            "SELECT after_ord, reason, detail, created_at FROM gaps "
            "WHERE person_id=? ORDER BY after_ord", (person_id,))
        return [{"ord": int(r["after_ord"]), "after_ord": int(r["after_ord"]),
                 "reason": r["reason"], "detail": r["detail"],
                 "at": r["created_at"]} for r in rows]
