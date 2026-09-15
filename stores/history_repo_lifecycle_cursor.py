"""Lifecycle cursor — extracted from history_repo_lifecycle (H-C5 split)

Cursor handling, ≤150 LOC.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from stores.history_repo_cursor import CursorLadder
from stores.history_requests import WriteContext

log = logging.getLogger("chatbot")


class LifecycleCursor:
    def __init__(self, owner):
        self._owner = owner
        self._cursor = CursorLadder(owner)

    async def get_cursor(self, person_id: int) -> dict:
        row = await self._owner.db.fetchone("SELECT * FROM cursors WHERE person_id=?", (person_id,))
        if not row:
            return {
                "person_id": person_id,
                "last_ord": 0,
                "dom_count": 0,
                "head_sig": "",
                "tail_sig": "",
                "head_any": "",
                "tail_any": "",
                "tail_fps": [],
                "tail_keys": [],
                "bootstrapped": False,
                "full_scan_complete": False,
                "full_scan_at": "",
            }
        data = dict(row)
        try:
            data["tail_fps"] = json.loads(data.get("tail_fps") or "[]")
        except Exception:
            data["tail_fps"] = []
        try:
            data["tail_keys"] = json.loads(data.get("tail_keys") or "[]")
        except Exception:
            data["tail_keys"] = []
        data["bootstrapped"] = bool(data.get("bootstrapped"))
        data["full_scan_complete"] = bool(data.get("full_scan_complete"))
        return data

    async def reset_cursor(self, nick: str) -> None:
        person_id = await self._owner.ensure_person(nick)
        await self._owner.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, tail_sig, head_any, tail_any, tail_fps, tail_keys, bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,?,0,'','','','','[]','[]',0,0,'',?) ON CONFLICT(person_id) DO UPDATE SET dom_count=0, head_sig='', tail_sig='', head_any='', tail_any='', tail_fps='[]', tail_keys='[]', bootstrapped=0, full_scan_complete=0, full_scan_at='', updated_at=excluded.updated_at",
            (person_id, await self._last_ord(person_id), datetime.now().isoformat(timespec="seconds")),
        )
        await self._owner.db.commit()

    async def _last_ord(self, person_id: int) -> int:
        return await self._cursor._last_ord(person_id)

    async def mark_backfilled(self, nick_or_id) -> None:
        person_id = int(nick_or_id) if isinstance(nick_or_id, int) else await self._owner.ensure_person(str(nick_or_id))
        stamp = datetime.now().isoformat(timespec="seconds")
        await self._owner.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, tail_sig, head_any, tail_any, tail_fps, tail_keys, bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,0,0,'','','','','[]','[]',0,1,?,?) ON CONFLICT(person_id) DO UPDATE SET full_scan_complete=1, full_scan_at=excluded.full_scan_at, updated_at=excluded.updated_at",
            (person_id, stamp, stamp),
        )
        await self._owner.db.commit()

    async def _resequence(self, person_id: int) -> None:
        return await self._cursor._resequence(person_id)

    async def _after_write(self, ctx: WriteContext) -> None:
        return await self._cursor._after_write(ctx)

    async def _recount(self, person_id: int, my_nick: str = "") -> None:
        return await self._cursor._recount(person_id, my_nick)

    async def _touch_cursor(self, ctx: WriteContext) -> None:
        return await self._cursor._touch_cursor(ctx)
