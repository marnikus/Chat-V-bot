"""Aligning a collected batch with what is stored, then writing it.

The append half of `stores/history_repo.py`. `AppendPlanner` decides which
rows of a batch are new (fingerprint + resolved day, so the same sentence on
two days is two rows), reuses the empty slots the trash left behind instead of
restarting the numbering, fills the UI row, syncs FTS and records a `gaps`
line when the alignment was lost. `append` never overwrites a stored line.

State stays on the aggregate: `db`, `media` and `session_id` are read off the
`HistoryRepo` at call time.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

from stores.history_models import (MAX_LIVE_ITEMS, AppendResult, MessageRecord)
from stores.history_repo_identity import (_as_record, align_batch,
                                          resolve_days)

log = logging.getLogger("chatbot")


class AppendPlanner:
    """Aligning a collected batch with what is stored, then writing it."""

    def __init__(self, owner):
        """`owner` is the `HistoryRepo` this part borrows state from."""
        self._owner = owner

    async def append(self, nick: str, records: Iterable, my_nick: str = "",
                     align: bool = True, expect_idx: Optional[int] = None,
                     dom_count: int = 0, head_sig: Optional[str] = None,
                     tail_sig: Optional[str] = None,
                     now: Optional[datetime] = None,
                     session_id: str = "",
                     head_any: Optional[str] = None,
                     tail_any: Optional[str] = None,
                     prepend: bool = False) -> AppendResult:  # quality-override: loc=54 params=13 cc=11 reason=signature mirrors HistoryRepo.append, the store keyword API
        """Archive one collected batch. See `HistoryRepo.append` for the
        contract; the steps are `_align`, `_write_rows` and `_after_write`."""
        now = now or datetime.now()
        person_id = await self._owner.ensure_person(nick)
        recs = [_as_record(r) for r in (records or [])]
        result = AppendResult(person_id=person_id)

        if not recs:
            return await self._report_unchanged(person_id, result, dom_count,
                                                head_sig, tail_sig, head_any,
                                                tail_any)
        if prepend:
            return await self._prepend(person_id, recs, my_nick, now,
                                       dom_count, head_sig, tail_sig,
                                       session_id, nick=nick,
                                       head_any=head_any, tail_any=tail_any)

        cursor = await self._owner.get_cursor(person_id)
        start, gap, reason = self._align([r.dup_key for r in recs], cursor,
                                         recs, align, expect_idx)
        days = resolve_days([r.ts_display for r in recs], now)
        last_ord = await self._owner._last_ord(person_id)
        result.first_ord = last_ord + 1
        if gap:
            await self._record_gap(person_id, last_ord, reason,
                                   f"expected idx {expect_idx}, got "
                                   f"{recs[0].idx}" if reason == "dom_jump"
                                   else "")

        added, last_ord = await self._write_rows(
            person_id, recs[start:], days[start:], my_nick, nick, session_id,
            last_ord, result)
        await self._owner.db.commit()

        await self._owner._after_write(person_id, my_nick, dom_count, head_sig,
                                tail_sig, bootstrapped=True,
                                head_any=head_any, tail_any=tail_any)
        person = await self._owner.get_person_by_id(person_id)
        result.added = added
        result.skipped = len(recs) - added
        result.gap = gap
        result.reason = reason
        result.last_ord = last_ord
        result.total = int(person["message_count"]) if person else 0
        return result

    async def _report_unchanged(self, person_id: int, result: AppendResult,
                                dom_count: int, head_sig, tail_sig, head_any,
                                tail_any) -> AppendResult:
        """An empty batch is still a sighting: it moves the cursor."""
        await self._owner._touch_cursor(person_id, dom_count, head_sig, tail_sig,
                                 head_any, tail_any)
        person = await self._owner.get_person_by_id(person_id)
        result.total = int(person["message_count"]) if person else 0
        result.last_ord = await self._owner._last_ord(person_id)
        return result

    def _align(self, batch_keys: list, cursor: dict, recs: list,
               align: bool, expect_idx: Optional[int]) -> tuple:
        """Where the batch continues the stored conversation, if at all.

        `start` is the index of the first new record; `gap` says the stored
        tail and the batch share nothing, so the batch is appended whole and a
        `gaps` row records the hole.
        """
        start, gap, reason = 0, False, ""
        if align:
            tail = cursor.get("tail_keys") or cursor.get("tail_fps") or []
            alignment = align_batch(batch_keys, tail)
            start = alignment.start
            gap, reason = alignment.gap, alignment.reason
        elif expect_idx is not None and recs[0].idx != expect_idx:
            gap, reason = True, "dom_jump"
        return start, gap, reason

    async def _write_rows(self, person_id: int, pending: list, days: list,
                          my_nick: str, nick: str, session_id: str,
                          last_ord: int, result: AppendResult) -> tuple:
        """Insert the genuinely new lines of the batch, oldest first.

        Timestamp + content is the identity. `fp` keeps its occurrence number
        for diagnostics, but must never cause a re-read to insert a second
        copy of a line that is already stored.
        """
        known = await self._existing_dup_keys(person_id,
                                              [r.dup_key for r in pending])
        stamp = datetime.now().isoformat(timespec="seconds")
        added = 0
        slots: dict = {}
        slot_rows: Optional[list] = None
        for rec, day in zip(pending, days):
            dup_key = rec.dup_key
            if dup_key in known:
                continue
            # a media line that was parsed before its <img> rendered left an
            # EMPTY slot behind; the real payload fills that slot in place
            # instead of archiving the message twice (Bug #2, 2026-09-07)
            if slot_rows is None:
                slot_rows = await self._empty_slot_rows(person_id)
            slot_id = await self._take_empty_slot(person_id, rec, slots,
                                                  day=day, rows=slot_rows)
            known.add(dup_key)
            if slot_id is not None:
                media_id = await self._owner._media_id(rec, nick, day)
                await self._fill_slot(slot_id, rec, media_id)
                added += 1
                await self._collect(result, rec, await self._ord_of(slot_id),
                                    day, my_nick, media_id)
                continue
            media_id = await self._owner._media_id(rec, nick, day)
            assigned = last_ord + 1
            if await self._insert_message(person_id, assigned, rec, day,
                                          my_nick, media_id, session_id,
                                          stamp):
                added += 1
                last_ord = assigned
                await self._collect(result, rec, assigned, day, my_nick,
                                    media_id)
        return added, last_ord

    async def _collect(self, result: AppendResult, rec: MessageRecord,
                       ord_value: int, day: str, my_nick: str,
                       media_id) -> None:
        """The live rows a caller gets back — capped at `MAX_LIVE_ITEMS`."""
        if len(result.records) < MAX_LIVE_ITEMS:
            result.records.append(await self._owner._ui_record(
                rec, ord_value, day, my_nick, media_id))

    async def _insert_message(self, person_id: int, ord_value: int,
                              rec: MessageRecord, day: str, my_nick: str,
                              media_id, session_id: str, stamp: str) -> bool:
        """One `messages` row. False when the unique index already has it."""
        cur = await self._owner.db.execute(
            "INSERT OR IGNORE INTO messages("
            "person_id, ord, fp, direction, from_nick, my_nick, kind, "
            "text, text_lc, media_id, ts_display, ts_resolved, day, "
            "ts_exact, occ, dom_idx, session_id, created_at, dup_key) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?)",
            (person_id, ord_value, rec.fp, rec.direction, rec.from_nick,
             my_nick or "", rec.kind, rec.text, (rec.text or "").lower(),
             media_id, rec.ts_display, f"{day} {rec.ts_display or '00:00'}",
             day, rec.occ, rec.idx, session_id or self._owner.session_id,
             stamp, rec.dup_key))
        return bool(cur.rowcount)

    async def _prepend(self, person_id: int, recs, my_nick: str,
                       now: datetime, dom_count: int,
                       head_sig: Optional[str], tail_sig: Optional[str],
                       session_id: str, nick: str = "",
                       head_any: Optional[str] = None,
                       tail_any: Optional[str] = None) -> AppendResult:
        """Backfill OLDER lines that appeared above what we already stored.

        Their `ord` must come before everything we have, so the existing rows
        are shifted up by however many genuinely new lines we found.
        """
        result = AppendResult(person_id=person_id)
        days = resolve_days([r.ts_display for r in recs], now)
        fresh = await self._fresh_rows(person_id, recs, days)
        result.skipped = len(recs) - len(fresh)
        if fresh:
            fills, inserts = await self._plan_prepend(person_id, fresh, nick)
            if inserts:
                await self._owner.db.execute(
                    "UPDATE messages SET ord = ord + ? WHERE person_id=?",
                    (len(inserts), person_id))
            stamp = datetime.now().isoformat(timespec="seconds")
            position = 0
            for rec, day in inserts:
                position += 1
                media_id = await self._owner._media_id(rec, nick, day)
                if await self._insert_message(person_id, position, rec, day,
                                              my_nick, media_id, session_id,
                                              stamp):
                    result.added += 1
                    await self._collect(result, rec, position, day, my_nick,
                                        media_id)
            for rec, day, slot_id, media_id in fills:
                await self._fill_slot(slot_id, rec, media_id)
                result.added += 1
                await self._collect(result, rec, await self._ord_of(slot_id),
                                    day, my_nick, media_id)
            await self._owner.db.commit()
        await self._owner._after_write(person_id, my_nick, dom_count, head_sig,
                                tail_sig, bootstrapped=True,
                                head_any=head_any, tail_any=tail_any)
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
        slots: dict = {}
        slot_rows = await self._empty_slot_rows(person_id)
        fills: list = []          # (rec, day, slot_id, media_id)
        inserts: list = []        # (rec, day)
        for rec, day in fresh:
            slot_id = await self._take_empty_slot(person_id, rec, slots,
                                                  day=day,
                                                  rows=slot_rows)
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

    async def _take_empty_slot(self, person_id: int, rec: MessageRecord,
                               used: dict, day: str = "",
                               rows: Optional[list] = None) -> Optional[int]:
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
        if rows is None:
            rows = await self._empty_slot_rows(person_id)
        want = self._owner._slot_key(rec) + ((day or "")[:10],)
        for row in rows:
            rid = int(row.get("id") or 0)
            if rid in used:
                continue
            if self._owner._slot_row_key(row) == want:
                used[rid] = True
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

    async def _ord_of(self, row_id: int) -> int:
        return int(await self._owner.db.scalar("SELECT ord FROM messages WHERE id=?",
                                        (row_id,), 0))

    async def _record_gap(self, person_id: int, after_ord: int, reason: str,
                          detail: str = "") -> None:
        await self._owner.db.execute(
            "INSERT INTO gaps(person_id, after_ord, reason, detail, created_at)"
            " VALUES(?,?,?,?,?)",
            (person_id, after_ord, reason or "unknown", detail,
             datetime.now().isoformat(timespec="seconds")))
        await self._owner.db.commit()

    async def record_gap(self, nick_or_id, after_ord: int, reason: str,
                         detail: str = "") -> None:
        """Note a known hole in a conversation (cap, lost alignment, …)."""
        person_id = (int(nick_or_id) if isinstance(nick_or_id, int)
                     else await self._owner.ensure_person(str(nick_or_id)))
        await self._record_gap(person_id, after_ord, reason, detail)
