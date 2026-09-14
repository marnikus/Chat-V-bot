"""The prepend / empty-slot planner (Round H step H-C4).

One named concept: backfilling *older* messages into an archive that already
has newer ones. `_plan_prepend` works out which rows are new, which fall into
a gap the archive already recorded, and which can take an empty ord slot;
`_take_empty_slot` / `_fill_slot` place them; `_existing_dup_keys` and
`_query_dup_keys` are the dedupe lookups both paths share.

Split out of `stores/history_repo_append.py` by the plan's H-C4 rule.
`AppendPlanner` keeps the forward append path; this mixin inherits into it,
so `HistoryRepo.append` and its request objects are unchanged.

Import direction: `stores.history_requests` for the append request; nothing
imports back.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional
from stores.history_models import (MAX_LIVE_ITEMS, AppendResult, MessageRecord)
from stores.history_repo_identity import (_as_record, align_batch,
                                          resolve_days)
from stores.history_requests import (AlignSpec, AppendRequest, PlacedRecord,
                                     PrependRequest, RowBatch, SlotSearch,
                                     WriteContext)



class PrependPlannerMixin:
    """Plan and place older rows; mixed into ``AppendPlanner``."""

    async def _prepend(self, req: PrependRequest) -> AppendResult:
        """Backfill OLDER lines that appeared above what we already stored.

        Their `ord` must come before everything we have, so the existing rows
        are shifted up by however many genuinely new lines we found.
        """
        ctx = req.ctx
        person_id = ctx.person_id
        result = AppendResult(person_id=person_id)
        days = resolve_days([r.ts_display for r in req.recs], req.now)
        fresh = await self._fresh_rows(person_id, req.recs, days)
        result.skipped = len(req.recs) - len(fresh)
        if fresh:
            fills, inserts = await self._plan_prepend(person_id, fresh,
                                                      req.nick)
            if inserts:
                await self._owner.db.execute(
                    "UPDATE messages SET ord = ord + ? WHERE person_id=?",
                    (len(inserts), person_id))
            stamp = datetime.now().isoformat(timespec="seconds")
            position = 0
            for rec, day in inserts:
                position += 1
                media_id = await self._owner._media_id(rec, req.nick, day)
                placed = PlacedRecord(rec, position, day, ctx.my_nick, media_id)
                if await self._insert_message(person_id, placed,
                                              req.session_id, stamp):
                    result.added += 1
                    await self._collect(result, placed)
            for rec, day, slot_id, media_id in fills:
                await self._fill_slot(slot_id, rec, media_id)
                result.added += 1
                await self._collect(result, PlacedRecord(
                    rec, await self._ord_of(slot_id), day, ctx.my_nick,
                    media_id))
            await self._owner.db.commit()
        await self._owner._after_write(ctx)
        person = await self._owner.get_person_by_id(person_id)
        result.total = int(person["message_count"]) if person else 0
        result.last_ord = await self._owner._last_ord(person_id)
        result.first_ord = 1
        return result

    async def _fresh_rows(self, person_id: int, recs, days) -> list:
        """The (record, day) pairs this person does not have yet."""
        known = await self._existing_dup_keys(person_id,
                                              [r.dup_key for r in recs])
        fresh = []
        for rec, day in zip(recs, days):
            if rec.dup_key in known:
                continue
            known.add(rec.dup_key)
            fresh.append((rec, day))
        return fresh

    async def _plan_prepend(self, person_id: int, fresh: list,
                            nick: str) -> tuple:
        """Split the fresh lines into slot fills and true inserts.

        A media line whose first parse predated its <img> left an empty slot
        somewhere in the stored range: fill it where it is instead of
        inserting a duplicate row (Bug #2, 2026-09-07).
        """
        search = SlotSearch(person_id, {},
                            await self._empty_slot_rows(person_id))
        fills: list = []          # (rec, day, slot_id, media_id)
        inserts: list = []        # (rec, day)
        for rec, day in fresh:
            slot_id = await self._take_empty_slot(rec, day, search)
            if slot_id is not None:
                fills.append((rec, day, slot_id,
                              await self._owner._media_id(rec, nick, day)))
            else:
                inserts.append((rec, day))
        return fills, inserts

    async def _existing_dup_keys(self, person_id: int, keys) -> set:
        """The subset of `keys` already stored for this person.

        Chunked so a 5000-message bootstrap does not blow SQLite's parameter
        limit, and so a small heartbeat does not read the whole table.
        """
        out: set = set()
        batch = []
        for key in keys:
            batch.append(str(key or ""))
            if len(batch) >= 400:
                out |= await self._query_dup_keys(person_id, batch)
                batch = []
        if batch:
            out |= await self._query_dup_keys(person_id, batch)
        return out

    async def _query_dup_keys(self, person_id: int, keys: list) -> set:
        placeholders = ",".join("?" for _ in keys)
        rows = await self._owner.db.fetchall(
            f"SELECT dup_key FROM messages WHERE person_id=? "
            f"AND dup_key IN ({placeholders})",
            [person_id] + keys)
        return {r[0] for r in rows if r[0]}

    async def _empty_slot_rows(self, person_id: int) -> list:
        """Every payload-less row of this person, in conversation order.

        Matching happens in Python: SQLite's `lower()` folds ASCII only, so
        a Cyrillic nick like `Хорошо Все` would never equal its own
        lower-cased record key inside a WHERE clause. Hidden (soft-deleted)
        rows are never filled: an "added" row must be one the user can see
        (Bug 4, 2026-09-08).
        """
        return await self._owner.db.fetchdicts(
            "SELECT id, direction, from_nick, ts_display, day FROM messages "
            "WHERE person_id=? AND deleted_at='' "
            "AND media_id IS NULL AND text='' "
            "ORDER BY ord", (person_id,))

    async def _take_empty_slot(self, rec: MessageRecord, day: str,
                               search: SlotSearch) -> Optional[int]:
        """The id of the next payload-less row matching this record.

        Any record that now carries a payload may fill its slot: a media
        line whose `app-chat-image` had not rendered, AND a text line whose
        `span.message` had not rendered when the node was first parsed (the
        agent re-parses such nodes since v10, but rows saved before that
        stay behind as empty rows — Bug 2, 2026-09-08). Matching is strict:
        direction + author + the on-screen clock, consumed in `ord` order,
        and the resolved calendar day is part of the key so a NEW message at
        16:24 cannot fill a slot left by yesterday's 16:24. A payload-less
        record never fills anything.
        """
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

    async def _fill_slot(self, slot_id: int, rec: MessageRecord,
                         media_id: Optional[int]) -> None:
        """Upgrade one empty row in place: same line, real payload."""
        await self._owner.db.execute(
            "UPDATE messages SET kind=?, text=?, text_lc=?, media_id=?, "
            "dup_key=?, fp=?, media_recovered_at=? WHERE id=?",
            (rec.kind, rec.text, (rec.text or "").lower(), media_id,
             rec.dup_key, rec.ensure_fp(),
             datetime.now().isoformat(timespec="seconds"), slot_id))
