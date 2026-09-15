"""The read side of the archive: pages, search, stats, the user database.

Part of the `history_bridge` family (facade: `bridge/history_bridge.py`,
Round H step H-B1). Every function receives the bridge as its host and
answers through its signals — the `req_id` the JS caller passed travels
into the payload and back out on the matching signal, which is what keeps
two concurrent windows from receiving each other's pages.

The bridge stays the wire (every @Slot name, signature and signal
unchanged); this module holds the coroutines those slots schedule.
"""

from __future__ import annotations

import json

from backend.history_query import (
    DEFAULT_LIMIT, DEFAULT_SORT, PersonPageRequest,
)


def _person_request(opts: dict) -> PersonPageRequest:
    """The UI's JSON blob as a `PersonPageRequest`.

    Lives here rather than on the wire facade (Round J step J-1): it is the
    read side's input shape, and the facade is down to the signals and the
    `@Slot` table. `dir` defaults to `""` — the sort key's *natural*
    direction — so a payload written before the sortable headers existed
    means exactly what it meant.
    """
    return PersonPageRequest(
        q=str(opts.get("q") or ""),
        limit=int(opts.get("limit") or DEFAULT_LIMIT),
        offset=int(opts.get("offset") or 0),
        sort=str(opts.get("sort") or DEFAULT_SORT),
        dir=str(opts.get("dir") or ""),
        include_deleted=bool(opts.get("include_deleted")))


async def history_page(bridge, req_id: str, nick: str, anchor_json) -> None:
    """One page of a person's messages — newest-first, or around an anchor.

    `history_open` and `history_page` are the same worker: the slot only
    differs in what JS calls the payload (options vs paging anchor).
    """
    opts = bridge._json_arg(anchor_json)
    service = bridge.ctx.archive
    limit = int(opts.get("limit") or
                service.preview_settings().get("page_size", 50))
    if opts.get("around") is not None:
        payload = await service.query.around(
            nick, int(opts["around"]),
            radius=int(opts.get("radius") or 25))
        payload["stats"] = await service.query.person_stats(nick)
        payload["my_nick"] = service.my_nick
    else:
        payload = await service.page(
            nick,
            before_ord=(int(opts["before_ord"])
                        if opts.get("before_ord") is not None else None),
            after_ord=(int(opts["after_ord"])
                       if opts.get("after_ord") is not None else None),
            limit=limit)
    payload["req_id"] = req_id
    payload["preview"] = service.preview_settings()
    bridge.history_page_ready.emit(req_id, json.dumps(payload,
                                                      ensure_ascii=False))


async def history_search(bridge, req_id: str, query_json) -> None:
    """Search inside one person (the default) or across the whole archive."""
    opts = bridge._json_arg(query_json)
    service = bridge.ctx.archive
    query = str(opts.get("q") or opts.get("query") or "")
    limit = int(opts.get("limit") or 100)
    if str(opts.get("scope") or "person") == "person":
        payload = await service.query.search_person(
            str(opts.get("nick") or ""), query, limit=limit,
            offset=int(opts.get("offset") or 0))
        payload["scope"] = "person"
    else:
        payload = await service.query.search_global(query, limit=limit)
        payload["scope"] = "global"
    payload["req_id"] = req_id
    bridge.history_search_ready.emit(req_id, json.dumps(payload,
                                                        ensure_ascii=False))


async def history_stats(bridge, req_id: str, nick: str) -> None:
    payload = await bridge.ctx.archive.query.person_stats(nick)
    payload["req_id"] = req_id
    bridge.history_stats_ready.emit(req_id, json.dumps(payload,
                                                       ensure_ascii=False))


async def userdb_page(bridge, req_id: str, query_json) -> None:
    """One page of the all-time user database, with label pills attached.

    Takes the JS blob, not a built request: decoding the payload is this
    side's job now, so the wire facade never has to know the request shape.
    """
    req = _person_request(bridge._json_arg(query_json))
    payload = await bridge.ctx.archive.query.list_persons(req)
    payload["req_id"] = req_id
    payload["my_nick"] = bridge.ctx.archive.my_nick
    labels = bridge.ctx.people.labels_for_nicks(
        [item.get("nick") for item in payload.get("items") or []])
    for item in payload.get("items") or []:
        item["labels"] = labels.get(item.get("nick"), [])
    bridge.userdb_page_ready.emit(req_id, json.dumps(payload,
                                                     ensure_ascii=False))


async def userdb_stats(bridge, req_id: str) -> None:
    payload = await bridge.ctx.archive.query.db_stats()
    payload["req_id"] = req_id
    payload.update(await bridge.ctx.archive.media.cache_usage())
    bridge.userdb_page_ready.emit(req_id, json.dumps(payload,
                                                     ensure_ascii=False))
