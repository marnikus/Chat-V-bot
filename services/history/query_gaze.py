"""History query — gaze + undo + page (H-C5 split)

Gaze loading, meta flag, undo, page, ≤120 LOC.
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("chatbot")
_GAZE_VER = 1


class HistoryQueryGaze:
    async def load_gaze(self) -> None:
        try:
            rows = await self.db.fetchdicts("SELECT key, value FROM gaze_data")
        except Exception as exc:
            log.debug("gaze load skipped: %s", exc)
            return
        data = {row["key"]: row["value"] for row in rows}
        if not data:
            return
        if data.get("partner"):
            self.collector._nick = str(data["partner"])
        for field in ("added", "total", "last_sync_added", "last_sync_count"):
            try:
                setattr(self.collector, "_" + field, int(data.get(field)))
            except (TypeError, ValueError):
                pass
        if data.get("last_sync_reason"):
            self.collector._last_sync_reason = str(data["last_sync_reason"])

    async def get_meta_flag(self, key: str) -> bool:
        try:
            value = await self.db.get_meta(key, None)
            return value is not None and str(value) != ""
        except Exception:
            return False

    async def load_world_undo(self) -> list[dict]:
        if not self.db.is_open:
            return []
        try:
            rows = await self.db.fetchall("SELECT seq, kind, value FROM undo_history ORDER BY seq")
        except Exception as exc:
            log.warning("undo load from %s failed: %s", self.db.path, exc)
            return []
        out = []
        for seq, kind, value in rows:
            try:
                out.append({"seq": int(seq), "kind": str(kind), "value": json.loads(str(value))})
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        return out

    async def page(self, nick: str, **kwargs) -> dict:
        payload = await self.query.page(nick, **kwargs)
        payload["stats"] = await self.query.person_stats(nick)
        payload["my_nick"] = self.my_nick
        return payload
