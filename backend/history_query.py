"""Read path of the message archive — facade over request + projection + search.

Search has two back-ends: FTS5 when SQLite offers it, a `text_lc LIKE` scan
when it does not. Both fold case for Cyrillic — `text_lc` is lower-cased in
Python, because SQLite's own LIKE folds ASCII only.

Back-end lives in `history_query_search.py` (H-B2), row projection in
`history_query_projection.py` (H-B2b), request value in
`history_query_request.py`. This module keeps the `HistoryQuery` surface.
"""
# ideal-size: 300 lines reason=facade over request + projection + search family (3 modules)

from __future__ import annotations

from typing import Optional

from stores.history_db import HistoryDB
from backend.history_query_projection import (
    _FIELD_SPECS, _FIELD_SPECS_TAIL, _apply_specs, _day_bounds,
    _item_media, _my_nicks, _person_item, _stat_int,
)
from backend.history_query_request import (
    DEFAULT_LIMIT, DEFAULT_SORT, MAX_LIMIT, SORT_COLUMNS, SORT_TIEBREAK, PersonPageRequest,
)
from backend.history_query_search import _fts_query, _like_escape, _snippet, search

__all__ = ["PersonPageRequest","HistoryQuery","SORT_COLUMNS","DEFAULT_SORT","SORT_TIEBREAK",
           "DEFAULT_LIMIT","MAX_LIMIT","_fts_query","_like_escape","_snippet","search",
           "_person_item","_apply_specs","_item_media","_stat_int","_day_bounds","_my_nicks",
           "_FIELD_SPECS","_FIELD_SPECS_TAIL"]

class HistoryQuery:
    """Every read the UI performs against the archive."""
    def __init__(self, db: HistoryDB):
        self.db = db
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
    _SELECT = ("SELECT m.*, md.url AS media_url, md.kind AS media_kind, "
               "md.state AS media_state, md.cache_path AS cache_path "
               "FROM messages m LEFT JOIN media md ON md.id = m.media_id ")
    _COUNT_ALIVE = "SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at=''"
    async def page(self, nick: str, before_ord: Optional[int] = None,
                   after_ord: Optional[int] = None,
                   limit: int = DEFAULT_LIMIT) -> dict:
        limit = self._clamp(limit)
        person = await self._person_row(nick)
        empty = {"nick": nick, "items": [], "has_more": False,
                 "has_newer": False, "total": 0, "gaps": [], "missing": True,
                 "my_nicks": []}
        if not person:
            return empty
        pid = int(person["id"])
        total = int(await self.db.scalar(self._COUNT_ALIVE, (pid,), 0))
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
            "SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at='' AND ord<?",
            (pid, first if items else 0), 0)) if items else False
        has_newer = bool(await self.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at='' AND ord>?",
            (pid, last), 0)) if items else False
        return {"nick": person["nick"], "items": items, "has_more": has_more,
                "has_newer": has_newer, "total": total, "gaps": await self.gaps(pid),
                "missing": False, "my_nicks": _my_nicks(person)}
    async def around(self, nick: str, ord_: int, radius: int = 25) -> dict:
        person = await self._person_row(nick)
        if not person:
            return {"nick": nick, "items": [], "anchor_ord": ord_,
                    "missing": True, "has_more": False, "has_newer": False,
                    "total": 0, "gaps": []}
        pid = int(person["id"])
        rows = await self.db.fetchdicts(
            self._SELECT + "WHERE m.person_id=? AND m.deleted_at='' "
            "AND m.ord BETWEEN ? AND ? ORDER BY m.ord",
            (pid, int(ord_) - int(radius), int(ord_) + int(radius)))
        items = [self._item(r) for r in rows]
        return {"nick": person["nick"], "items": items, "anchor_ord": int(ord_),
                "missing": False,
                "total": int(await self.db.scalar(self._COUNT_ALIVE, (pid,), 0)),
                "has_more": bool(items) and items[0]["ord"] > 1,
                "has_newer": bool(await self.db.scalar(
                    "SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at='' AND ord>?",
                    (pid, items[-1]["ord"] if items else 0), 0)),
                "gaps": await self.gaps(pid)}
    async def gaps(self, person_id: int) -> list[dict]:
        rows = await self.db.fetchdicts(
            "SELECT after_ord, reason, detail, created_at FROM gaps WHERE person_id=? ORDER BY after_ord",
            (person_id,))
        return [{"ord": int(r["after_ord"]), "after_ord": int(r["after_ord"]),
                 "reason": r["reason"], "detail": r["detail"], "at": r["created_at"]} for r in rows]
    async def search_person(self, nick: str, query: str,
                            limit: int = DEFAULT_LIMIT, offset: int = 0) -> dict:
        person = await self._person_row(nick)
        if not person:
            return {"items": [], "total": 0, "has_more": False, "nick": nick, "query": query}
        rows, total = await self._search(int(person["id"]), query,
                                         self._clamp(limit), int(offset or 0))
        items = []
        for row in rows:
            item = self._item(row)
            item["snippet"] = _snippet(item["text"], query.strip())
            items.append(item)
        return {"nick": person["nick"], "query": query, "items": items,
                "total": total, "has_more": total > (int(offset or 0) + len(items))}
    async def search_global(self, query: str, limit: int = 200, per_person: int = 20) -> dict:
        rows, total = await self._search(None, query, self._clamp(limit), 0)
        groups: dict[str, dict] = {}
        for row in rows:
            item = self._item(row)
            nick = dict(row).get("nick") or ""
            group = groups.setdefault(nick, {"nick": nick, "items": [], "total": 0})
            group["total"] += 1
            if len(group["items"]) < per_person:
                group["items"].append({
                    "ord": item["ord"], "day": item["day"], "time": item["time"],
                    "dir": item["dir"], "from": item["from"], "kind": item["kind"],
                    "text": item["text"], "snippet": _snippet(item["text"], query.strip())})
        ordered = sorted(groups.values(), key=lambda g: -g["total"])
        return {"query": query, "groups": ordered, "total": total, "persons": len(ordered)}
    async def _search(self, person_id: Optional[int], query: str, limit: int, offset: int):
        return await search(self.db, person_id, query, limit, offset)
    async def list_persons(self, req: PersonPageRequest) -> dict:
        limit = self._clamp(req.limit)
        offset = max(0, int(req.offset or 0))
        where, where_params = req.where()
        order, order_params = req.order()
        total = int(await self.db.scalar(
            f"SELECT COUNT(*) FROM persons WHERE {where}", where_params, 0))
        rows = await self.db.fetchdicts(
            f"SELECT * FROM persons WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            where_params + order_params + [limit, offset])
        items = [_person_item(row, _my_nicks(row)) for row in rows]
        return {"items": items, "total": total, "has_more": total > offset + len(items),
                "offset": offset, "limit": limit, "query": req.q, "sort": req.sort,
                "dir": req.resolved_dir()}
    async def db_stats(self) -> dict:
        persons = int(await self.db.scalar(
            "SELECT COUNT(*) FROM persons WHERE deleted_at IS NULL", (), 0))
        return {
            "persons": persons,
            "persons_deleted": int(await self.db.scalar(
                "SELECT COUNT(*) FROM persons WHERE deleted_at IS NOT NULL", (), 0)),
            "messages": int(await self.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE deleted_at=''", (), 0)),
            "messages_hidden": int(await self.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE deleted_at<>''", (), 0)),
            "text_bytes": int(await self.db.scalar(
                "SELECT COALESCE(SUM(LENGTH(text)),0) FROM messages WHERE deleted_at=''", (), 0)),
            "media": int(await self.db.scalar("SELECT COUNT(*) FROM media", (), 0)),
            "media_cached": int(await self.db.scalar(
                "SELECT COUNT(*) FROM media WHERE state='cached'", (), 0)),
            "media_bytes": int(await self.db.scalar(
                "SELECT SUM(bytes) FROM media WHERE state='cached'", (), 0)),
            "gaps": int(await self.db.scalar("SELECT COUNT(*) FROM gaps", (), 0)),
            "fts": bool(self.db.fts_enabled), "db_bytes": self.db.file_size(), "path": self.db.path,
        }
    async def person_stats(self, nick: str) -> dict:
        person = await self._person_row(nick)
        if not person:
            return {"nick": nick, "missing": True, "message_count": 0, "my_nicks": []}
        data = dict(person)
        pid = int(data["id"])
        first_day, last_day, days = await _day_bounds(self.db, pid)
        return {
            "nick": data["nick"], "missing": False,
            "message_count": _stat_int(data, "message_count"),
            "messages": _stat_int(data, "message_count"),
            "in_count": _stat_int(data, "in_count"),
            "out_count": _stat_int(data, "out_count"),
            "media_count": _stat_int(data, "media_count"),
            "my_nicks": _my_nicks(person),
            "first_seen": data.get("first_seen") or "", "last_seen": data.get("last_seen") or "",
            "first_day": first_day, "last_day": last_day, "days": days,
            "hidden": int(await self.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at<>''", (pid,), 0)),
            "deleted": bool(data.get("deleted_at")), "gaps": await self.gaps(pid),
        }
