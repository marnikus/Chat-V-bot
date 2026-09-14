"""Empty-slot planner — extracted from AppendPlanner (H-C4).

One named responsibility: prepend/empty-slot planner (_prepend, _plan_prepend,
_take_empty_slot, _empty_slot_rows). Keeps AppendPlanner orchestration,
moves slot logic here.

Design: AREA_C H-C4 — helper named by responsibility, ≤200 LOC.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from stores.history_models import MessageRecord
from stores.history_requests import SlotSearch

log = logging.getLogger("chatbot")


class SlotPlanner:
    def __init__(self, owner):
        self._owner = owner

    async def _empty_slot_rows(self, person_id: int) -> list:
        """Every payload-less row of this person, in conversation order."""
        return await self._owner.db.fetchdicts(
            "SELECT id, direction, from_nick, ts_display, day FROM messages "
            "WHERE person_id=? AND deleted_at='' "
            "AND media_id IS NULL AND text='' "
            "ORDER BY ord",
            (person_id,),
        )

    async def _take_empty_slot(self, rec: MessageRecord, day: str, search: SlotSearch) -> Optional[int]:
        """The id of the next payload-less row matching this record."""
        if not rec.media_url and not (rec.text or "").strip():
            return None
        if search.rows is None:
            search.rows = await self._empty_slot_rows(search.person_id)
        want = self._owner._slot_key(rec) + ((day or "")[:10],)
        for row in search.rows:
            rid = int(row.get("id") or 0)
            if rid in search.used:
                continue
            if self._owner._slot_row_key(row) == want:
                search.used[rid] = True
                return rid
        return None

    async def _fill_slot(self, slot_id: int, rec: MessageRecord, media_id: Optional[int]) -> None:
        """Upgrade one empty row in place: same line, real payload."""
        await self._owner.db.execute(
            "UPDATE messages SET kind=?, text=?, text_lc=?, media_id=?, dup_key=?, fp=?, media_recovered_at=? WHERE id=?",
            (
                rec.kind,
                rec.text,
                (rec.text or "").lower(),
                media_id,
                rec.dup_key,
                rec.ensure_fp(),
                datetime.now().isoformat(timespec="seconds"),
                slot_id,
            ),
        )

    async def _ord_of(self, row_id: int) -> int:
        return int(await self._owner.db.scalar("SELECT ord FROM messages WHERE id=?", (row_id,), 0))

    async def _plan_prepend(self, person_id: int, fresh: list, nick: str) -> tuple:
        """Split the fresh lines into slot fills and true inserts."""
        search = SlotSearch(person_id, {}, await self._empty_slot_rows(person_id))
        fills: list = []
        inserts: list = []
        for rec, day in fresh:
            slot_id = await self._take_empty_slot(rec, day, search)
            if slot_id is not None:
                fills.append((rec, day, slot_id, await self._owner._media_id(rec, nick, day)))
            else:
                inserts.append((rec, day))
        return fills, inserts
