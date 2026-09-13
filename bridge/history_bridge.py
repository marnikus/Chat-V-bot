"""HistoryBridge — the message archive: reads, deletions, media, clipboard.

Reads hit an async SQLite database, so a @Slot cannot answer inline: JS
passes a `req_id` and Python answers on a signal carrying the same id
(two windows can ask for two pages at once without answers crossing).
The archive service (services/history_service.py) owns the database.
"""

# Round H (H1) ended the §18.5 exemption this file used to carry. The claim was
# that the QWebChannel wire contract pinned the size -- it pins the SLOT NAMES,
# which is a different thing. The delete and media slots moved to mixins in
# bridge/history_delete.py and bridge/history_media.py; HistoryBridge still
# inherits them, so all 28 slots and signals remain on the one QObject and the
# frontend sees no change (proved by comparing staticMetaObject before and
# after). 563 lines / MI 25.8 -> 278 lines / MI 50.4.

from __future__ import annotations

import json
import logging
import os

from PySide6.QtCore import QObject, Signal, Slot

from core.events import LogMessage, UserDbChanged
from backend.history_query import (
    DEFAULT_LIMIT, DEFAULT_SORT, PersonPageRequest,
)
from bridge.history_delete import HistoryDeleteMixin
from bridge.history_media import HistoryMediaMixin
from services.world_events import run_when_world_open

log = logging.getLogger("chatbot")


def _person_request(opts: dict) -> PersonPageRequest:
    """The UI's JSON blob as a `PersonPageRequest`.

    Kept out of the `work()` closure so that closure stays a short, readable
    "fetch, decorate, emit" sequence.

    `dir` defaults to `""` — the sort key's *natural* direction — so a payload
    written before the sortable headers existed means exactly what it meant.
    """
    return PersonPageRequest(
        q=str(opts.get("q") or ""),
        limit=int(opts.get("limit") or DEFAULT_LIMIT),
        offset=int(opts.get("offset") or 0),
        sort=str(opts.get("sort") or DEFAULT_SORT),
        dir=str(opts.get("dir") or ""),
        include_deleted=bool(opts.get("include_deleted")))


def _attach_labels(people, payload: dict) -> None:
    """Decorate each person row in `payload` with its labels, in place.

    Looked up in ONE batched call for the whole page rather than per row:
    the user database lists hundreds of people and a query each would make
    the panel's first paint visibly slow.
    """
    nicks = [item.get("nick") for item in payload.get("items") or []]
    labels = people.labels_for_nicks(nicks)
    for item in payload.get("items") or []:
        item["labels"] = labels.get(item.get("nick"), [])


class HistoryBridge(HistoryDeleteMixin, HistoryMediaMixin, QObject):
    history_page_ready = Signal(str, str)    # req_id, JSON page
    history_search_ready = Signal(str, str)  # req_id, JSON results
    history_stats_ready = Signal(str, str)   # req_id, JSON stats
    userdb_page_ready = Signal(str, str)     # req_id, JSON persons / stats
    userdb_changed = Signal(str)             # JSON {action, nick}
    media_ready = Signal(str, str)           # req_id, JSON media info
    history_error = Signal(str, str)         # scope, message

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        ctx.bus.subscribe(UserDbChanged,
                          lambda e: self.userdb_changed.emit(e.payload))

    # ── guarded async runner ─────────────────────────────────────
    def _run_async(self, scope: str, coro) -> None:
        self._schedule(run_when_world_open(
            scope, coro, getattr(self.ctx.archive, "db", None),
            self.history_error.emit))

    @staticmethod
    def _schedule(coro) -> bool:
        try:
            import asyncio
            asyncio.ensure_future(coro)
            return True
        except RuntimeError:
            coro.close()
            return False

    @staticmethod
    def _json_arg(raw, default=None):
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return dict(default or {})
        return data if isinstance(data, dict) else dict(default or {})

    def _reply(self, signal, req_id: str, payload: dict, **extra) -> None:
        """Answer one request: stamp the id, add `extra`, emit as JSON.

        Every read slot ends this way. The req_id is stamped INSIDE the
        payload as well as passed alongside it because the UI correlates
        replies by reading the body -- a signal argument alone is lost once
        the JSON reaches JavaScript. ensure_ascii is off throughout: nicks
        are routinely non-Latin and escaping them would change what the
        history window displays.
        """
        payload["req_id"] = req_id
        payload.update(extra)
        signal.emit(req_id, json.dumps(payload, ensure_ascii=False))

    def _need_archive(self, scope: str, req_id: str = "") -> bool:
        if self.ctx.archive is None:
            self.history_error.emit(scope, "the message archive is not "
                                            "running")
            return False
        return True

    def _nick_for(self, scope: str, nick) -> str:
        """A whitespace-normalised nick, or "" when the call cannot proceed.

        Folds the two preconditions every person-scoped slot shares: the nick
        must survive normalisation, and the archive must be running. The
        archive failure is REPORTED on history_error and the blank nick is
        not -- an empty argument is the UI asking for nothing, while a
        missing archive is a state the user needs to be told about. Returning
        "" for both lets the caller write one falsy check.
        """
        clean = " ".join(str(nick or "").split()).strip()
        if not clean:
            return ""
        return clean if self._need_archive(scope, "") else ""

    # ── person history ───────────────────────────────────────────
    @Slot(str, str, str)
    def history_open(self, req_id, nick, options_json):
        if not self._need_archive("history_open", req_id):
            return
        opts = self._json_arg(options_json)
        self._run_async("history_open",
                        self._history_page(req_id, nick, opts))

    @Slot(str, str, str)
    def history_page(self, req_id, nick, anchor_json):
        if not self._need_archive("history_page", req_id):
            return
        opts = self._json_arg(anchor_json)
        self._run_async("history_page",
                        self._history_page(req_id, nick, opts))

    async def _history_page(self, req_id, nick, opts):
        service = self.ctx.archive
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
        self._reply(self.history_page_ready, req_id, payload,
                    preview=service.preview_settings())

    @Slot(str, str)
    def history_search(self, req_id, query_json):
        if not self._need_archive("history_search", req_id):
            return
        opts = self._json_arg(query_json)
        self._run_async("history_search", self._history_search(req_id, opts))

    async def _history_search(self, req_id, opts):
        service = self.ctx.archive
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
        self._reply(self.history_search_ready, req_id, payload)

    @Slot(str, str)
    def history_stats(self, req_id, nick):
        if not self._need_archive("history_stats", req_id):
            return

        async def work():
            payload = await self.ctx.archive.query.person_stats(nick)
            self._reply(self.history_stats_ready, req_id, payload)
        self._run_async("history_stats", work())

    # ── the all-time user database ───────────────────────────────
    @Slot(str, str)
    def userdb_page(self, req_id, query_json):
        if not self._need_archive("userdb_page", req_id):
            return
        opts = self._json_arg(query_json)
        req = _person_request(opts)

        async def work():
            payload = await self.ctx.archive.query.list_persons(req)
            _attach_labels(self.ctx.people, payload)
            self._reply(self.userdb_page_ready, req_id, payload,
                        my_nick=self.ctx.archive.my_nick)
        self._run_async("userdb_page", work())

    @Slot(str)
    def userdb_stats(self, req_id):
        if not self._need_archive("userdb_stats", req_id):
            return

        async def work():
            payload = await self.ctx.archive.query.db_stats()
            self._reply(self.userdb_page_ready, req_id, payload,
                        **await self.ctx.archive.media.cache_usage())
        self._run_async("userdb_stats", work())

    # ── deleting from the archive (all reversible, RULE 12) ──────


    # ── helpers ──────────────────────────────────────────────────


    # ── media + clipboard ────────────────────────────────────────


    # ── archive settings ─────────────────────────────────────────
    @Slot(result=str)
    def get_history_settings(self):
        if self.ctx.archive is None:
            return json.dumps(self.ctx.config.get_copy("history",
                                                       default={}))
        return json.dumps(self.ctx.archive.settings(), ensure_ascii=False)

    @Slot(str)
    def save_history_settings(self, settings_json):
        patch = self._json_arg(settings_json)
        if self.ctx.archive is None:
            stored = self.ctx.config.get_copy("history", default={})
            stored.update(patch)
            self.ctx.config.set("history", stored)
            self.ctx.config.save()
            return
        self.ctx.archive.apply_settings(patch)
        self.ctx.bus.emit(LogMessage(message="💾 Archive settings saved",
                                     level="info"))

    # ── My Nick detection (reads the live page through the archive) ─
    @Slot(str)
    def detect_my_nick(self, req_id):
        if not self._need_archive("detect_my_nick", req_id):
            return

        async def work():
            state = await self.ctx.archive.parser.state()
            self.history_stats_ready.emit(req_id, json.dumps(
                {"req_id": req_id, "detected": state.get("me") or "",
                 "partner": state.get("partner") or ""},
                ensure_ascii=False))
        self._run_async("detect_my_nick", work())
