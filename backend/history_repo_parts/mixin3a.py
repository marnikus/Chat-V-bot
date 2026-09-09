"""History repo 3a append (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional, Iterable

class HistoryRepoMixin3a:
    async def append(self, nick: str, records: Iterable, my_nick: str = "",
                     align: bool = True, expect_idx: Optional[int] = None,
                     dom_count: int = 0, head_sig: Optional[str] = None,
                     tail_sig: Optional[str] = None,
                     now: Optional[datetime] = None,
                     session_id: str = "",
                     head_any: Optional[str] = None,
                     tail_any: Optional[str] = None,
                     prepend: bool = False) -> AppendResult:
        now = now or datetime.now()
        person_id = await self.ensure_person(nick)
        recs = [_as_record(r) for r in (records or [])]
        result = AppendResult(person_id=person_id)

        if not recs:
            await self._touch_cursor(person_id, dom_count, head_sig, tail_sig,
                                     head_any, tail_any)
            person = await self.get_person_by_id(person_id)
            result.total = int(person["message_count"]) if person else 0
            result.last_ord = await self._last_ord(person_id)
            return result

        if prepend:
            return await self._prepend(person_id, recs, my_nick, now,
                                       dom_count, head_sig, tail_sig,
                                       session_id, nick=nick,
                                       head_any=head_any, tail_any=tail_any)

        cursor = await self.get_cursor(person_id)
        batch_keys = [r.dup_key for r in recs]
        gap, reason, start = False, "", 0
        if align:
            tail = cursor.get("tail_keys") or cursor.get("tail_fps") or []
            alignment = align_batch(batch_keys, tail)
            start, gap, reason = alignment.start, alignment.gap, alignment.reason
        elif expect_idx is not None and recs[0].idx != expect_idx:
            gap, reason = True, "dom_jump"

        days = resolve_days([r.ts_display for r in recs], now)
        last_ord = await self._last_ord(person_id)
        result.first_ord = last_ord + 1
        if gap:
            await self._record_gap(person_id, last_ord, reason,
                                   f"expected idx {expect_idx}, got "
                                   f"{recs[0].idx}" if reason == "dom_jump"
                                   else "")

        # Timestamp + content is the identity. `fp` keeps its occurrence
        # number for diagnostics, but must never cause a re-read to insert a
        # second copy of a line that is already stored.
        pending = recs[start:]
        known = await self._existing_dup_keys(person_id,
                                              [r.dup_key for r in pending])

        stamp = datetime.now().isoformat(timespec="seconds")
        added = 0
        slots: dict = {}
        slot_rows: Optional[list] = None
        for rec, day in zip(pending, days[start:]):
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
            if slot_id is not None:
                media_id = await self._media_id(rec, nick, day)
                await self._fill_slot(slot_id, rec, media_id)
                known.add(dup_key)
                added += 1
                if len(result.records) < MAX_LIVE_ITEMS:
                    result.records.append(await self._ui_record(
                        rec, await self._ord_of(slot_id), day, my_nick,
                        media_id))
                continue
            known.add(dup_key)
            media_id = await self._media_id(rec, nick, day)
            assigned = last_ord + 1
            cur = await self.db.execute(
                "INSERT OR IGNORE INTO messages("
                "person_id, ord, fp, direction, from_nick, my_nick, kind, "
                "text, text_lc, media_id, ts_display, ts_resolved, day, "
                "ts_exact, occ, dom_idx, session_id, created_at, dup_key) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?)",
                (person_id, assigned, rec.fp, rec.direction, rec.from_nick,
                 my_nick or "", rec.kind, rec.text, (rec.text or "").lower(),
                 media_id, rec.ts_display, f"{day} {rec.ts_display or '00:00'}",
                 day, rec.occ, rec.idx, session_id or self.session_id, stamp,
                 dup_key))
            if cur.rowcount:
                added += 1
                last_ord = assigned
                if len(result.records) < MAX_LIVE_ITEMS:
                    result.records.append(await self._ui_record(
                        rec, assigned, day, my_nick, media_id))
        await self.db.commit()

        await self._after_write(person_id, my_nick, dom_count, head_sig,
                                tail_sig, bootstrapped=True,
                                head_any=head_any, tail_any=tail_any)
        person = await self.get_person_by_id(person_id)
        result.added = added
        result.skipped = len(recs) - added
        result.gap = gap
        result.reason = reason
        result.last_ord = last_ord
        result.total = int(person["message_count"]) if person else 0
        return result

