"""Media / UI record — extracted from history_repo_identity (H-C5 split)

≤120 LOC.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from stores.history_models import MessageRecord
from stores.history_repo_identity_helpers import (
    _UI_BODY_SPECS,
    _UI_HEAD_SPECS,
    _UI_TAIL_SPECS,
    _record_fields,
    _ui_media_payload,
)
from stores.history_requests import PlacedRecord

log = logging.getLogger("chatbot")
_MEDIA_VER = 1


class ConversationIdentityMedia:
    def __init__(self, owner):
        self._owner = owner

    async def _ui_record(self, placed: PlacedRecord) -> dict:
        rec = placed.rec
        media = await self._ui_media(placed.media_id, rec) if placed.media_id else None
        item = {"ord": int(placed.ord_value or 0)}
        item.update(_record_fields(rec, _UI_HEAD_SPECS))
        item["my_nick"] = placed.my_nick or ""
        item.update(_record_fields(rec, _UI_BODY_SPECS))
        item["media"] = media
        item.update(_record_fields(rec, _UI_TAIL_SPECS))
        item["day"] = placed.day or ""
        item["occ"] = int(rec.occ or 0)
        return item

    async def _ui_media(self, media_id, rec: MessageRecord):
        row = await self._read_media_row(media_id)
        if not row:
            return None
        return _ui_media_payload(row, media_id, rec)

    async def _read_media_row(self, media_id):
        if self._owner.media is not None:
            return await self._owner.media.get(media_id)
        row = await self._owner.db.fetchone("SELECT * FROM media WHERE id=?", (media_id,))
        return dict(row) if row else None

    async def _media_id(self, rec: MessageRecord, nick: str = "", day: str = "") -> Optional[int]:
        if not rec.media_url:
            return None
        if self._owner.media is not None:
            return await self._owner.media.register(rec.media_url, rec.media_kind or rec.kind, nick=nick, day=day)
        stamp = datetime.now().isoformat(timespec="seconds")
        await self._owner.db.execute(
            "INSERT INTO media(url, kind, state, ref_count, created_at, last_used) VALUES(?,?,'pending',1,?,?) "
            "ON CONFLICT(url) DO UPDATE SET ref_count=ref_count+1, last_used=excluded.last_used",
            (rec.media_url, rec.media_kind or rec.kind or "image", stamp, stamp),
        )
        row = await self._owner.db.fetchone("SELECT id FROM media WHERE url=?", (rec.media_url,))
        return int(row[0]) if row else None
