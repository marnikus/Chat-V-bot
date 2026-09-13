"""Search inside one conversation and across the whole archive.

`SearchMixin` owns the two interchangeable back-ends (FTS5 when available, a
`text_lc LIKE` scan otherwise) and the person/global search entry points.
"""

from __future__ import annotations

import logging
from typing import Optional

from .constants import DEFAULT_LIMIT
from .search_text import _fts_query, _like_escape, _snippet

log = logging.getLogger("chatbot")


class SearchMixin:
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
