"""The archive's read surface: person history, search, stats, my nick.

`ReadsMixin` answers the request/response slots — JS passes a `req_id`
and the answer comes back on the signal carrying the same id, so two
windows can ask for two pages at once without the answers crossing.
`detect_my_nick` belongs here because it is the same shape: one read of
the live page (through the archive's parser) answered on
`history_stats_ready`.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Slot


class ReadsMixin:
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
        payload["req_id"] = req_id
        payload["preview"] = service.preview_settings()
        self.history_page_ready.emit(req_id, json.dumps(payload,
                                                        ensure_ascii=False))

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
        payload["req_id"] = req_id
        self.history_search_ready.emit(req_id, json.dumps(payload,
                                                          ensure_ascii=False))

    @Slot(str, str)
    def history_stats(self, req_id, nick):
        if not self._need_archive("history_stats", req_id):
            return

        async def work():
            payload = await self.ctx.archive.query.person_stats(nick)
            payload["req_id"] = req_id
            self.history_stats_ready.emit(req_id, json.dumps(
                payload, ensure_ascii=False))
        self._run_async("history_stats", work())

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
