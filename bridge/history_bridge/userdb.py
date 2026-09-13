"""The Full User Database window: the person page and the header counters.

`UserDbMixin` turns the window's sort/search request into a
`PersonPageRequest`, decorates the rows with their label pills and
answers on `userdb_page_ready`. Reads go through
`ctx.archive.query` (`backend/history_query/`).
"""

from __future__ import annotations

import json

from PySide6.QtCore import Slot

from .support import _person_request


class UserDbMixin:
    # ── the all-time user database ───────────────────────────────
    @Slot(str, str)
    def userdb_page(self, req_id, query_json):
        if not self._need_archive("userdb_page", req_id):
            return
        opts = self._json_arg(query_json)
        req = _person_request(opts)

        async def work():
            payload = await self.ctx.archive.query.list_persons(req)
            payload["req_id"] = req_id
            payload["my_nick"] = self.ctx.archive.my_nick
            labels = self.ctx.people.labels_for_nicks(
                [item.get("nick") for item in payload.get("items") or []])
            for item in payload.get("items") or []:
                item["labels"] = labels.get(item.get("nick"), [])
            self.userdb_page_ready.emit(req_id, json.dumps(
                payload, ensure_ascii=False))
        self._run_async("userdb_page", work())

    @Slot(str)
    def userdb_stats(self, req_id):
        if not self._need_archive("userdb_stats", req_id):
            return

        async def work():
            payload = await self.ctx.archive.query.db_stats()
            payload["req_id"] = req_id
            payload.update(await self.ctx.archive.media.cache_usage())
            self.userdb_page_ready.emit(req_id, json.dumps(
                payload, ensure_ascii=False))
        self._run_async("userdb_stats", work())
