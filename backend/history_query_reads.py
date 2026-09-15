"""The archive read path's SQL: paging, around, gaps, search, the counters.

Part of the `history_*` read family (facade: `backend/history_query.py`,
Round J step J-2). Every function here takes the facade (`q`) and answers the
question its name asks, against `q.db`:

* `page` / `around` — the two window reads, oldest-first inside the page, with
  the stability rule that keeps paging honest while the collector appends
  underneath (`SORT_TIEBREAK` makes the order total; the `has_more` /
  `has_newer` counters come from `ord`, not from a row count, so a page cannot
  shift under the user);
* `gaps` — the collection gaps of one person;
* `search_person` / `search_global` / `search` — the two entry points and the
  thin binding to the FTS/LIKE back-end in `history_query_search.py`;
* `list_persons` / `db_stats` / `person_stats` — the Full User Database page
  and the two header counter blocks.

Why module functions: the facade's method signatures are a frozen interface
(Area B design §6) and the API snapshot pins them to `backend.history_query`,
so the methods stay on the class as one-line delegations while the SQL lives
here. This is the same shape Round H step H-B1 gave the archive bridge.
"""

from __future__ import annotations

from typing import Optional

from backend import history_query_rows as rowmap
from backend import history_query_search as search_backend
from backend.history_query_search import _snippet

DEFAULT_LIMIT = rowmap.DEFAULT_LIMIT

#: the message row plus its joined media block, for both window reads
SELECT_JOIN = ("SELECT m.*, md.url AS media_url, md.kind AS media_kind, "
               "md.state AS media_state, md.cache_path AS cache_path "
               "FROM messages m LEFT JOIN media md ON md.id = m.media_id ")
#: soft-deleted rows are invisible to every read (they exist only so a
#: single Ctrl+Z can bring them back)
COUNT_ALIVE = ("SELECT COUNT(*) FROM messages WHERE person_id=? AND "
               "deleted_at=''")

async def page(q, nick: str, before_ord: Optional[int] = None,
       after_ord: Optional[int] = None,
       limit: int = DEFAULT_LIMIT) -> dict:
    """One screen of a conversation, oldest-first inside the page."""
    limit = rowmap.clamp(limit)
    person = await rowmap.person_row(q.db, nick)
    empty = {"nick": nick, "items": [], "has_more": False,
             "has_newer": False, "total": 0, "gaps": [], "missing": True,
             "my_nicks": []}
    if not person:
        return empty
    pid = int(person["id"])
    total = int(await q.db.scalar(
        COUNT_ALIVE, (pid,), 0))

    if after_ord is not None:
        row_rows = await q.db.fetchdicts(
            SELECT_JOIN + "WHERE m.person_id=? AND m.deleted_at='' "
            "AND m.ord>? ORDER BY m.ord LIMIT ?",
            (pid, int(after_ord), limit))
    elif before_ord is not None:
        row_rows = await q.db.fetchdicts(
            SELECT_JOIN + "WHERE m.person_id=? AND m.deleted_at='' "
            "AND m.ord<? ORDER BY m.ord DESC LIMIT ?",
            (pid, int(before_ord), limit))
        row_rows = list(reversed(row_rows))
    else:
        row_rows = await q.db.fetchdicts(
            SELECT_JOIN + "WHERE m.person_id=? AND m.deleted_at='' "
            "ORDER BY m.ord DESC LIMIT ?", (pid, limit))
        row_rows = list(reversed(row_rows))

    items = [rowmap.item(r) for r in row_rows]
    first = items[0]["ord"] if items else 0
    last = items[-1]["ord"] if items else 0
    has_more = bool(await q.db.scalar(
        "SELECT COUNT(*) FROM messages WHERE person_id=? AND "
        "deleted_at='' AND ord<?",
        (pid, first if items else 0), 0)) if items else False
    has_newer = bool(await q.db.scalar(
        "SELECT COUNT(*) FROM messages WHERE person_id=? AND "
        "deleted_at='' AND ord>?",
        (pid, last), 0)) if items else False
    return {
        "nick": person["nick"],
        "items": items,
        "has_more": has_more,
        "has_newer": has_newer,
        "total": total,
        "gaps": await gaps(q, pid),
        "missing": False,
        "my_nicks": rowmap.my_nicks(person),
    }


async def around(q, nick: str, ord_: int, radius: int = 25) -> dict:
    person = await rowmap.person_row(q.db, nick)
    if not person:
        return {"nick": nick, "items": [], "anchor_ord": ord_,
                "missing": True, "has_more": False, "has_newer": False,
                "total": 0, "gaps": []}
    pid = int(person["id"])
    row_rows = await q.db.fetchdicts(
        SELECT_JOIN + "WHERE m.person_id=? AND m.deleted_at='' "
        "AND m.ord BETWEEN ? AND ? "
        "ORDER BY m.ord", (pid, int(ord_) - int(radius),
                           int(ord_) + int(radius)))
    items = [rowmap.item(r) for r in row_rows]
    return {
        "nick": person["nick"],
        "items": items,
        "anchor_ord": int(ord_),
        "missing": False,
        "total": int(await q.db.scalar(COUNT_ALIVE, (pid,), 0)),
        "has_more": bool(items) and items[0]["ord"] > 1,
        "has_newer": bool(await q.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE person_id=? AND "
            "deleted_at='' AND ord>?",
            (pid, items[-1]["ord"] if items else 0), 0)),
        "gaps": await gaps(q, pid),
    }


async def gaps(q, person_id: int) -> list[dict]:
    rows = await q.db.fetchdicts(
        "SELECT after_ord, reason, detail, created_at FROM gaps "
        "WHERE person_id=? ORDER BY after_ord", (person_id,))
    return [{"ord": int(r["after_ord"]), "after_ord": int(r["after_ord"]),
             "reason": r["reason"], "detail": r["detail"],
             "at": r["created_at"]} for r in rows]

# ── search ───────────────────────────────────────────────────


async def search_person(q, nick: str, query: str, limit: int = DEFAULT_LIMIT,
                offset: int = 0) -> dict:
    person = await rowmap.person_row(q.db, nick)
    if not person:
        return {"items": [], "total": 0, "has_more": False,
                "nick": nick, "query": query}
    found, total = await search(q, int(person["id"]), query,
                                rowmap.clamp(limit), int(offset or 0))
    items = []
    for row in found:
        item = rowmap.item(row)
        item["snippet"] = _snippet(item["text"], query.strip())
        items.append(item)
    return {"nick": person["nick"], "query": query, "items": items,
            "total": total,
            "has_more": total > (int(offset or 0) + len(items))}


async def search_global(q, query: str, limit: int = 200,
                        per_person: int = 20) -> dict:
    found, total = await search(q, None, query, rowmap.clamp(limit), 0)
    groups: dict[str, dict] = {}
    for row in found:
        item = rowmap.item(row)
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


async def search(q, person_id: Optional[int], query: str, limit: int,
                 offset: int):
    """Both entry points read through here; the FTS-or-LIKE decision itself
    is `history_query_search.search`."""
    return await search_backend.search(q.db, person_id, query, limit, offset)

# ── the user database window ─────────────────────────────────


async def list_persons(q, req) -> dict:
    """One page of the Full User Database, in the order the header asks.

    `req` carries the six options the UI sends as one blob. The response
    echoes the sort key verbatim plus the *resolved* direction, so the UI
    paints the right arrow without duplicating `SORT_COLUMNS` in
    JavaScript.

    The COUNT binds only the `where()` parameters; the page query binds
    `where()` + `order()` + limit/offset, in that order.
    """
    limit = rowmap.clamp(req.limit)
    offset = max(0, int(req.offset or 0))
    where, where_params = req.where()
    order, order_params = req.order()
    total = int(await q.db.scalar(
        f"SELECT COUNT(*) FROM persons WHERE {where}", where_params, 0))
    row_rows = await q.db.fetchdicts(
        f"SELECT * FROM persons WHERE {where} ORDER BY {order} "
        "LIMIT ? OFFSET ?", where_params + order_params + [limit, offset])
    items = [rowmap.person_item(row, rowmap.my_nicks(row))
             for row in row_rows]
    return {"items": items, "total": total,
            "has_more": total > offset + len(items),
            "offset": offset, "limit": limit, "query": req.q,
            "sort": req.sort, "dir": req.resolved_dir()}


async def db_stats(q) -> dict:
    persons = int(await q.db.scalar(
        "SELECT COUNT(*) FROM persons WHERE deleted_at IS NULL", (), 0))
    return {
        "persons": persons,
        "persons_deleted": int(await q.db.scalar(
            "SELECT COUNT(*) FROM persons WHERE deleted_at IS NOT NULL",
            (), 0)),
        "messages": int(await q.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE deleted_at=''", (), 0)),
        "messages_hidden": int(await q.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE deleted_at<>''", (), 0)),
        # alive messages only — consistent with the `messages` count,
        # so the read-out never mixes hidden (undoable) rows in
        "text_bytes": int(await q.db.scalar(
            "SELECT COALESCE(SUM(LENGTH(text)),0) FROM messages "
            "WHERE deleted_at=''", (), 0)),
        "media": int(await q.db.scalar(
            "SELECT COUNT(*) FROM media", (), 0)),
        "media_cached": int(await q.db.scalar(
            "SELECT COUNT(*) FROM media WHERE state='cached'", (), 0)),
        "media_bytes": int(await q.db.scalar(
            "SELECT SUM(bytes) FROM media WHERE state='cached'", (), 0)),
        "gaps": int(await q.db.scalar("SELECT COUNT(*) FROM gaps", (), 0)),
        "fts": bool(q.db.fts_enabled),
        "db_bytes": q.db.file_size(),
        "path": q.db.path,
    }


async def person_stats(q, nick: str) -> dict:
    person = await rowmap.person_row(q.db, nick)
    if not person:
        return {"nick": nick, "missing": True, "message_count": 0,
                "my_nicks": []}
    data = dict(person)
    pid = int(data["id"])
    first_day, last_day, days = await rowmap.day_bounds(q.db, pid)
    return {
        "nick": data["nick"],
        "missing": False,
        "message_count": rowmap.stat_int(data, "message_count"),
        "messages": rowmap.stat_int(data, "message_count"),
        "in_count": rowmap.stat_int(data, "in_count"),
        "out_count": rowmap.stat_int(data, "out_count"),
        "media_count": rowmap.stat_int(data, "media_count"),
        "my_nicks": rowmap.my_nicks(person),
        "first_seen": data.get("first_seen") or "",
        "last_seen": data.get("last_seen") or "",
        "first_day": first_day,
        "last_day": last_day,
        "days": days,
        "hidden": int(await q.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE person_id=? AND "
            "deleted_at<>''", (pid,), 0)),
        "deleted": bool(data.get("deleted_at")),
        "gaps": await gaps(q, pid),
    }
