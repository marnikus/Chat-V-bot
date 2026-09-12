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
import os
import re
from dataclasses import dataclass
from typing import Optional

from stores.history_db import HistoryDB

log = logging.getLogger("chatbot")

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
SNIPPET_RADIUS = 40

#: The Full User Database's sortable columns — key → the columns it orders
#: by, each with its **natural** direction: what a first click on that header
#: gives, and what every caller that sends no `dir` gets.
#:
#: This dict IS the whitelist. A `sort` that is not a key here falls back to
#: ``DEFAULT_SORT``, so no request text can ever reach `ORDER BY` — the same
#: discipline `_like_escape` / `_fts_query` apply to the search paths.
#:
#: `my_nicks` is a JSON array stored as text (`'["Me","Me2"]'`) and the column
#: shows it joined. Ordering the stored text needs no JSON1 extension (FTS5 is
#: already treated as optional here) and cannot fail on a hand-edited row; for
#: the common one-identity case it is exactly the displayed order. Known
#: wrinkle, pinned by a test: `["Me", "Old"]` sorts before `["Me"]`, because
#: `","` < `"]"`.
SORT_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "nick": (("nick_lc", "ASC"),),
    "msgs": (("message_count", "DESC"), ("last_seen", "DESC")),
    "media": (("media_count", "DESC"), ("last_seen", "DESC")),
    "first": (("first_seen", "ASC"),),
    "last": (("last_seen", "DESC"), ("message_count", "DESC")),
    "my_nick": (("my_nicks", "ASC"),),
    # historical spellings, kept so payloads written before the header sort
    # existed keep meaning exactly what they meant
    "messages": (("message_count", "DESC"), ("last_seen", "DESC")),
    "recent": (("last_seen", "DESC"), ("message_count", "DESC")),
}
DEFAULT_SORT = "recent"

#: Appended to every order. `LIMIT ? OFFSET ?` over a *partial* order lets
#: SQLite re-shuffle the ties between two queries, so a person could be served
#: twice or never while the user scrolls. `nick` is unique, which makes the
#: resulting order total.
SORT_TIEBREAK: tuple[str, ...] = ("nick_lc", "id")


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


@dataclass(frozen=True)
class PersonPageRequest:
    """One request for a page of the Full User Database.

    The UI sends these six options together in a single JSON blob, so they
    travel together: one frozen value instead of six parameters. Freezing it
    also means a request cannot be mutated between the bridge and the
    database, which makes a mismatched page impossible to explain away.

    The methods here own the SQL fragments, and none of them is built from
    request text — columns and directions are looked up in `SORT_COLUMNS`, and
    the nick is always a bound parameter.
    """

    q: str = ""
    limit: int = DEFAULT_LIMIT
    offset: int = 0
    sort: str = DEFAULT_SORT
    dir: str = ""
    include_deleted: bool = False

    # ── the pieces the caller asks about ────────────────────────

    def needle(self) -> str:
        """The lower-cased, trimmed search text — empty means 'no filter'."""
        return str(self.q or "").strip().lower()

    def spec(self) -> tuple[tuple[str, str], ...]:
        """The whitelisted columns for this key (the default if unknown)."""
        return SORT_COLUMNS.get(str(self.sort or ""),
                                SORT_COLUMNS[DEFAULT_SORT])

    def resolved_dir(self) -> str:
        """`"asc"` / `"desc"` — the direction actually applied.

        An empty (or unrecognised) `dir` means *the key's natural direction*,
        the direction of its first column. Reporting the resolved value back
        is what lets the header show the right arrow without duplicating
        `SORT_COLUMNS` in JavaScript.
        """
        asked = self._asked_dir()
        if asked:
            return asked
        return self.spec()[0][1].lower()

    # ── the SQL fragments ───────────────────────────────────────

    def where(self) -> tuple[str, list]:
        """The row filter and its parameters (nick bound, wildcards escaped)."""
        clause = "1=1" if self.include_deleted else "deleted_at IS NULL"
        needle = self.needle()
        if not needle:
            return clause, []
        return (clause + " AND nick_lc LIKE ? ESCAPE '\\'",
                ["%" + _like_escape(needle) + "%"])

    def order(self) -> tuple[str, list]:
        """The `ORDER BY` body and its parameters.

        While searching, relevance stays outermost: an exact prefix outranks a
        longer nick that merely contains the needle, and among equally good
        matches the shorter nick wins. Inside a tier the chosen column
        decides.

        The prefix-boost `LIKE` is a literal prefix, so its parameter differs
        from the `where()` one — callers bind this list *after* the where
        parameters.
        """
        body = self.columns()
        needle = self.needle()
        if not needle:
            return body, []
        return ("(nick_lc LIKE ? ESCAPE '\\') DESC, "
                f"LENGTH(nick_lc) ASC, {body}",
                [_like_escape(needle) + "%"])

    # ── internals ───────────────────────────────────────────────

    def _asked_dir(self) -> str:
        """The requested direction when it is a usable one, else `""`."""
        asked = str(self.dir or "").strip().lower()
        return asked if asked in ("asc", "desc") else ""

    def columns(self) -> str:
        """The `ORDER BY` column list — whitelist only, tiebreaker included.

        An explicit direction flips **every** column of the key, so the
        secondary column stays consistent with the primary one (`msgs`
        descending = busiest first, and among equals the *oldest* activity
        last).
        """
        asked = self._asked_dir()
        parts = [f"{column} {asked.upper() if asked else natural}"
                 for column, natural in self.spec()]
        used = {column for column, _ in self.spec()}
        parts += [f"{column} ASC"
                  for column in SORT_TIEBREAK if column not in used]
        return ", ".join(parts)


def _person_item(row, my_nicks: list) -> dict:
    """One person row, as the Full User Database shows it.

    A module function rather than a method: the mapping is a pure projection
    of one row, and `HistoryQuery` is already over its size budget.
    """
    data = dict(row)
    return {
        "id": int(data["id"]),
        "nick": data["nick"],
        "message_count": int(data.get("message_count") or 0),
        "in_count": int(data.get("in_count") or 0),
        "out_count": int(data.get("out_count") or 0),
        "media_count": int(data.get("media_count") or 0),
        "first_seen": data.get("first_seen") or "",
        "last_seen": data.get("last_seen") or "",
        "my_nicks": my_nicks,
        "deleted": bool(data.get("deleted_at")),
    }


#: (output keys, source key, default, as_int) — the row→UI-item field map.
#: Alias pairs share one source so the legacy and current spellings can never
#: disagree (UI contract; see backend_api_snapshot.json).
_FIELD_SPECS = (
    (("id",), "id", 0, True),
    (("ord",), "ord", 0, True),
    (("fp",), "fp", "", False),
    (("dir", "direction"), "direction", "in", False),
    (("from", "from_nick"), "from_nick", "", False),
    (("my_nick",), "my_nick", "", False),
    (("kind",), "kind", "text", False),
    (("text",), "text", "", False),
)
#: The fields after `media`, which the UI contract places between `text` and
#: `time` — two tables so that position survives the loop.
_FIELD_SPECS_TAIL = (
    (("time", "ts_display"), "ts_display", "", False),
    (("ts_resolved",), "ts_resolved", "", False),
    (("day",), "day", "", False),
    (("occ",), "occ", 0, True),
)


def _apply_specs(data: dict, specs) -> dict:
    """One group of the UI item, coalesced and aliased per a field spec."""
    out = {}
    for keys, source, default, as_int in specs:
        value = data.get(source) or default
        for key in keys:
            out[key] = int(value) if as_int else value
    return out


def _item_media(data: dict) -> dict | None:
    """The joined media block for one message row, or None."""
    if not data.get("media_id"):
        return None
    path = data.get("cache_path") or ""
    state = data.get("media_state") or "pending"
    # A cached row whose file vanished must not render as a broken
    # <img> from a dead local path: report it as missing so the UI
    # shows a "click to restore" marker instead.
    if path and not os.path.exists(path):
        state = "missing"
        path = ""
    return {"id": data.get("media_id"), "url": data.get("media_url"),
            "kind": data.get("media_kind") or data.get("kind"),
            "state": state, "path": path}


def _stat_int(data: dict, key: str) -> int:
    """One counter of a person row, tolerating NULL/absent."""
    return int(data.get(key) or 0)


async def _day_bounds(db, pid: int) -> tuple[str, str, int]:
    """(first_day, last_day, distinct days) over the visible messages.

    Module-level on purpose: `HistoryQuery` is already at the RULE 16
    method cap (enforced by tests/test_rule16_new_code.py through
    tools/metrics/rule16_gate.py), and this is a pure read over a db
    handle — it needs nothing from the instance.
    """
    row = await db.fetchone(
        "SELECT MIN(day) AS first_day, MAX(day) AS last_day, "
        "COUNT(DISTINCT day) AS days FROM messages WHERE person_id=? "
        "AND deleted_at=''", (pid,))
    if not row:
        return "", "", 0
    return (row["first_day"] or ""), (row["last_day"] or ""), int(row["days"] or 0)


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
