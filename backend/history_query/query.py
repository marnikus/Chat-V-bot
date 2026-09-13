"""`HistoryQuery` — every read the UI performs against the archive.

Owns the class itself: paging that stays stable while the collector appends
underneath, search inside one conversation and across the whole archive, the
master person list, and the header counters.

The class is NOT split further, deliberately. Its fourteen methods all read
`self.db` and share the `_SELECT` / `_COUNT_ALIVE` fragments — the LCOM is low
because the cohesion is real, and breaking it up by line count would raise
coupling to lower a number. What moved out is everything that does NOT touch
the database: the constants, the text escaping, the request object and the row
shaping, each now importable and testable on its own.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.history_query.request import PersonPageRequest
from backend.history_query.rows import (_FIELD_SPECS, _FIELD_SPECS_TAIL,
                                        _apply_specs, _day_bounds, _item_media,
                                        _person_item, _stat_int)
from backend.history_query.sorting import DEFAULT_LIMIT, MAX_LIMIT
from backend.history_query.sqltext import _fts_query, _like_escape, _snippet
from stores.history_db import HistoryDB

log = logging.getLogger("chatbot")

async def _page_rows(db, select, pid: int, before_ord, after_ord, limit: int):
    """The one page of rows the cursor asks for, always oldest-first.

    Three cursors, one shape. `after_ord` reads forwards and is already
    ascending; the other two read backwards so SQLite can walk the ord
    index from the newest end, and are reversed here. Reversing at the
    point of the query -- rather than leaving it to the caller -- is what
    lets the caller treat items[0] as the oldest row in every case.
    """
    where = "WHERE m.person_id=? AND m.deleted_at='' "
    if after_ord is not None:
        return await db.fetchdicts(
            select + where + "AND m.ord>? ORDER BY m.ord LIMIT ?",
            (pid, int(after_ord), limit))
    if before_ord is not None:
        rows = await db.fetchdicts(
            select + where +
            "AND m.ord<? ORDER BY m.ord DESC LIMIT ?",
            (pid, int(before_ord), limit))
    else:
        rows = await db.fetchdicts(
            select + where + "ORDER BY m.ord DESC LIMIT ?",
            (pid, limit))
    return list(reversed(rows))

async def _neighbour_flags(db, pid: int, items: list) -> tuple:
    """`(has_more, has_newer)` -- is there anything past either edge?

    An empty page has no edges to look past, so both are False without a
    query; that guard is why the counts below can index items directly.
    """
    if not items:
        return False, False
    sql = ("SELECT COUNT(*) FROM messages WHERE person_id=? AND "
           "deleted_at='' AND ord")
    older = await db.scalar(sql + "<?", (pid, items[0]["ord"]), 0)
    newer = await db.scalar(sql + ">?", (pid, items[-1]["ord"]), 0)
    return bool(older), bool(newer)


class HistoryQuery:
    """

from __future__ import annotations
Every read the UI performs against the archive."""

    def __init__(self, db: HistoryDB):
        self.db = db

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
        """One archive row as the UI item, key order and defaults intact."""
        data = dict(row)
        item = _apply_specs(data, _FIELD_SPECS)
        item["media"] = _item_media(data)
        item.update(_apply_specs(data, _FIELD_SPECS_TAIL))
        return item

    _SELECT = ("SELECT m.*, md.url AS media_url, md.kind AS media_kind, "
               "md.state AS media_state, md.cache_path AS cache_path "
               "FROM messages m LEFT JOIN media md ON md.id = m.media_id ")
    #: soft-deleted rows are invisible to every read (they exist only so a
    #: single Ctrl+Z can bring them back)
    _COUNT_ALIVE = ("SELECT COUNT(*) FROM messages WHERE person_id=? AND "
                    "deleted_at=''")

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

        items = [self._item(r) for r in
                 await _page_rows(self.db, self._SELECT, pid,
                                  before_ord, after_ord, limit)]
        has_more, has_newer = await _neighbour_flags(self.db, pid, items)
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

    # ── search ───────────────────────────────────────────────────
    async def search_person(self, nick: str, query: str,
                            limit: int = DEFAULT_LIMIT,
                            offset: int = 0) -> dict:
        person = await self._person_row(nick)
        if not person:
            return {"items": [], "total": 0, "has_more": False,
                    "nick": nick, "query": query}
        rows, total = await self._search(int(person["id"]), query,
                                         self._clamp(limit), int(offset or 0))
        items = []
        for row in rows:
            item = self._item(row)
            item["snippet"] = _snippet(item["text"], query.strip())
            items.append(item)
        return {"nick": person["nick"], "query": query, "items": items,
                "total": total,
                "has_more": total > (int(offset or 0) + len(items))}

    async def search_global(self, query: str, limit: int = 200,
                            per_person: int = 20) -> dict:
        rows, total = await self._search(None, query, self._clamp(limit), 0)
        groups: dict[str, dict] = {}
        for row in rows:
            item = self._item(row)
            nick = dict(row).get("nick") or ""
            group = groups.setdefault(nick, {"nick": nick, "items": [],
                                             "total": 0})
            group["total"] += 1
            if len(group["items"]) < per_person:
                group["items"].append({
                    "ord": item["ord"], "day": item["day"],
                    "time": item["time"], "dir": item["dir"],
                    "from": item["from"], "kind": item["kind"],
                    "text": item["text"],
                    "snippet": _snippet(item["text"], query.strip())})
        ordered = sorted(groups.values(), key=lambda g: -g["total"])
        return {"query": query, "groups": ordered, "total": total,
                "persons": len(ordered)}

    async def _search(self, person_id: Optional[int], query: str, limit: int,
                      offset: int):
        text = (query or "").strip()
        if not text:
            return [], 0
        where = "p.deleted_at IS NULL AND m.deleted_at=''"
        params: list = []
        if person_id is not None:
            where += " AND m.person_id=?"
            params.append(person_id)

        select = ("SELECT m.*, md.url AS media_url, md.kind AS media_kind, "
                  "md.state AS media_state, md.cache_path AS cache_path, "
                  "p.nick AS nick FROM messages m "
                  "JOIN persons p ON p.id = m.person_id "
                  "LEFT JOIN media md ON md.id = m.media_id ")

        if self.db.fts_enabled:
            match = _fts_query(text)
            if not match:
                return [], 0
            try:
                base = (select +
                        "JOIN messages_fts f ON f.rowid = m.id "
                        f"WHERE {where} AND messages_fts MATCH ? ")
                total = int(await self.db.scalar(
                    "SELECT COUNT(*) FROM messages m "
                    "JOIN persons p ON p.id = m.person_id "
                    "JOIN messages_fts f ON f.rowid = m.id "
                    f"WHERE {where} AND messages_fts MATCH ?",
                    params + [match], 0))
                rows = await self.db.fetchdicts(
                    base + "ORDER BY m.person_id, m.ord LIMIT ? OFFSET ?",
                    params + [match, limit, offset])
                return rows, total
            except Exception as e:                    # noqa: BLE001
                log.warning("FTS search failed (%s) — using LIKE", e)

        needle = "%" + _like_escape(text.lower()) + "%"
        total = int(await self.db.scalar(
            "SELECT COUNT(*) FROM messages m "
            "JOIN persons p ON p.id = m.person_id "
            f"WHERE {where} AND m.text_lc LIKE ? ESCAPE '\\'",
            params + [needle], 0))
        rows = await self.db.fetchdicts(
            select + f"WHERE {where} AND m.text_lc LIKE ? ESCAPE '\\' "
            "ORDER BY m.person_id, m.ord LIMIT ? OFFSET ?",
            params + [needle, limit, offset])
        return rows, total

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
