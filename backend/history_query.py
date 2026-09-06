"""Read path of the message archive.

Feeds the two new windows: chronological paging that stays stable while the
collector appends underneath, search inside one conversation and across the
whole archive, the master person list and the header counters.

Search has two interchangeable back-ends: FTS5 when SQLite offers it, a
`text_lc LIKE` scan when it does not. Both fold case for Cyrillic — the
`text_lc` column is lower-cased in Python, because SQLite's own LIKE folds
ASCII only.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from backend.history_db import HistoryDB

log = logging.getLogger("chatbot")

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
SNIPPET_RADIUS = 40


def _like_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("%", "\\%")
                .replace("_", "\\_"))


def _fts_query(raw: str) -> str:
    """Turn user input into a safe FTS5 MATCH expression.

    Every token is quoted, so `AND`, `*`, quotes and stray punctuation are
    data, never syntax.
    """
    tokens = [t for t in re.split(r"[^\w\u0400-\u04FF]+", raw or "") if t]
    if not tokens:
        return ""
    return " ".join('"%s"' % t.replace('"', '""') for t in tokens)


def _snippet(text: str, needle: str, radius: int = SNIPPET_RADIUS) -> str:
    body = text or ""
    if not needle:
        return body[: radius * 2]
    pos = body.lower().find(needle.lower())
    if pos < 0:
        return body[: radius * 2]
    start = max(0, pos - radius)
    end = min(len(body), pos + len(needle) + radius)
    return ("…" if start else "") + body[start:end] + ("…" if end < len(body)
                                                       else "")


class HistoryQuery:
    """Every read the UI performs against the archive."""

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
        data = dict(row)
        media = None
        if data.get("media_id"):
            media = {"id": data.get("media_id"), "url": data.get("media_url"),
                     "kind": data.get("media_kind") or data.get("kind"),
                     "state": data.get("media_state") or "pending",
                     "path": data.get("cache_path") or ""}
        return {
            "ord": int(data.get("ord") or 0),
            "fp": data.get("fp") or "",
            "dir": data.get("direction") or "in",
            "direction": data.get("direction") or "in",
            "from": data.get("from_nick") or "",
            "from_nick": data.get("from_nick") or "",
            "my_nick": data.get("my_nick") or "",
            "kind": data.get("kind") or "text",
            "text": data.get("text") or "",
            "media": media,
            "time": data.get("ts_display") or "",
            "ts_display": data.get("ts_display") or "",
            "ts_resolved": data.get("ts_resolved") or "",
            "day": data.get("day") or "",
            "occ": int(data.get("occ") or 0),
        }

    _SELECT = ("SELECT m.*, md.url AS media_url, md.kind AS media_kind, "
               "md.state AS media_state, md.cache_path AS cache_path "
               "FROM messages m LEFT JOIN media md ON md.id = m.media_id ")

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
            "SELECT COUNT(*) FROM messages WHERE person_id=?", (pid,), 0))

        if after_ord is not None:
            rows = await self.db.fetchdicts(
                self._SELECT + "WHERE m.person_id=? AND m.ord>? "
                "ORDER BY m.ord LIMIT ?", (pid, int(after_ord), limit))
        elif before_ord is not None:
            rows = await self.db.fetchdicts(
                self._SELECT + "WHERE m.person_id=? AND m.ord<? "
                "ORDER BY m.ord DESC LIMIT ?", (pid, int(before_ord), limit))
            rows = list(reversed(rows))
        else:
            rows = await self.db.fetchdicts(
                self._SELECT + "WHERE m.person_id=? ORDER BY m.ord DESC "
                "LIMIT ?", (pid, limit))
            rows = list(reversed(rows))

        items = [self._item(r) for r in rows]
        first = items[0]["ord"] if items else 0
        last = items[-1]["ord"] if items else 0
        has_more = bool(await self.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE person_id=? AND ord<?",
            (pid, first if items else 0), 0)) if items else False
        has_newer = bool(await self.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE person_id=? AND ord>?",
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
            self._SELECT + "WHERE m.person_id=? AND m.ord BETWEEN ? AND ? "
            "ORDER BY m.ord", (pid, int(ord_) - int(radius),
                               int(ord_) + int(radius)))
        items = [self._item(r) for r in rows]
        return {
            "nick": person["nick"],
            "items": items,
            "anchor_ord": int(ord_),
            "missing": False,
            "total": int(await self.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE person_id=?", (pid,), 0)),
            "has_more": bool(items) and items[0]["ord"] > 1,
            "has_newer": bool(await self.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE person_id=? AND ord>?",
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
        where = "p.deleted_at IS NULL"
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

    async def list_persons(self, q: str = "", limit: int = DEFAULT_LIMIT,
                           offset: int = 0, sort: str = "recent",
                           include_deleted: bool = False) -> dict:
        limit = self._clamp(limit)
        offset = max(0, int(offset or 0))
        where = "1=1" if include_deleted else "deleted_at IS NULL"
        params: list = []
        needle = (q or "").strip().lower()
        if needle:
            where += " AND nick_lc LIKE ? ESCAPE '\\'"
            params.append("%" + _like_escape(needle) + "%")

        order = {
            "messages": "message_count DESC, last_seen DESC",
            "nick": "nick_lc ASC",
            "first": "first_seen ASC",
            "recent": "last_seen DESC, message_count DESC",
        }.get(sort or "recent", "last_seen DESC, message_count DESC")
        if needle:
            order = ("(nick_lc LIKE ? ESCAPE '\\') DESC, LENGTH(nick_lc) ASC, "
                     + order)
            params.append(_like_escape(needle) + "%")

        total = int(await self.db.scalar(
            f"SELECT COUNT(*) FROM persons WHERE {where}",
            params[:1] if needle else [], 0))
        rows = await self.db.fetchdicts(
            f"SELECT * FROM persons WHERE {where} ORDER BY {order} "
            "LIMIT ? OFFSET ?", params + [limit, offset])
        items = []
        for row in rows:
            data = dict(row)
            items.append({
                "id": int(data["id"]),
                "nick": data["nick"],
                "message_count": int(data.get("message_count") or 0),
                "in_count": int(data.get("in_count") or 0),
                "out_count": int(data.get("out_count") or 0),
                "media_count": int(data.get("media_count") or 0),
                "first_seen": data.get("first_seen") or "",
                "last_seen": data.get("last_seen") or "",
                "my_nicks": self._my_nicks(row),
                "deleted": bool(data.get("deleted_at")),
            })
        return {"items": items, "total": total,
                "has_more": total > offset + len(items),
                "offset": offset, "limit": limit, "query": q, "sort": sort}

    async def db_stats(self) -> dict:
        persons = int(await self.db.scalar(
            "SELECT COUNT(*) FROM persons WHERE deleted_at IS NULL", (), 0))
        return {
            "persons": persons,
            "persons_deleted": int(await self.db.scalar(
                "SELECT COUNT(*) FROM persons WHERE deleted_at IS NOT NULL",
                (), 0)),
            "messages": int(await self.db.scalar(
                "SELECT COUNT(*) FROM messages", (), 0)),
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
        row = await self.db.fetchone(
            "SELECT MIN(day) AS first_day, MAX(day) AS last_day, "
            "COUNT(DISTINCT day) AS days FROM messages WHERE person_id=?",
            (pid,))
        return {
            "nick": data["nick"],
            "missing": False,
            "message_count": int(data.get("message_count") or 0),
            "messages": int(data.get("message_count") or 0),
            "in_count": int(data.get("in_count") or 0),
            "out_count": int(data.get("out_count") or 0),
            "media_count": int(data.get("media_count") or 0),
            "my_nicks": self._my_nicks(person),
            "first_seen": data.get("first_seen") or "",
            "last_seen": data.get("last_seen") or "",
            "first_day": (row["first_day"] if row else "") or "",
            "last_day": (row["last_day"] if row else "") or "",
            "days": int((row["days"] if row else 0) or 0),
            "deleted": bool(data.get("deleted_at")),
            "gaps": await self.gaps(pid),
        }
