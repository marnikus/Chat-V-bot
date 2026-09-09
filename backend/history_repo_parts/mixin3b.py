"""History repo 3b prepend (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional, Iterable

class HistoryRepoMixin3b:
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
        known = await self._existing_dup_keys(person_id,
                                              [r.dup_key for r in recs])
        fresh = []
        for rec, day in zip(recs, days):
            if rec.dup_key in known:
                continue
            known.add(rec.dup_key)
            fresh.append((rec, day))
        result.skipped = len(recs) - len(fresh)
        if fresh:
            # A media line whose first parse predated its <img> left an empty
            # slot somewhere in the stored range: fill it where it is instead
            # of inserting a duplicate row (Bug #2, 2026-09-07).
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
                                  await self._media_id(rec, nick, day)))
                else:
                    inserts.append((rec, day))
            if inserts:
                shift = len(inserts)
                await self.db.execute(
                    "UPDATE messages SET ord = ord + ? WHERE person_id=?",
                    (shift, person_id))
            stamp = datetime.now().isoformat(timespec="seconds")
            position = 0
            for rec, day in inserts:
                position += 1
                media_id = await self._media_id(rec, nick, day)
                cur = await self.db.execute(
                    "INSERT OR IGNORE INTO messages("
                    "person_id, ord, fp, direction, from_nick, my_nick, kind, "
                    "text, text_lc, media_id, ts_display, ts_resolved, day, "
                    "ts_exact, occ, dom_idx, session_id, created_at, dup_key) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?)",
                    (person_id, position, rec.fp, rec.direction, rec.from_nick,
                     my_nick or "", rec.kind, rec.text, (rec.text or "").lower(),
                     media_id, rec.ts_display,
                     f"{day} {rec.ts_display or '00:00'}", day, rec.occ,
                     rec.idx, session_id or self.session_id, stamp,
                     rec.dup_key))
                if cur.rowcount:
                    result.added += 1
                    if len(result.records) < MAX_LIVE_ITEMS:
                        result.records.append(await self._ui_record(
                            rec, position, day, my_nick, media_id))
            for rec, day, slot_id, media_id in fills:
                await self._fill_slot(slot_id, rec, media_id)
                result.added += 1
                if len(result.records) < MAX_LIVE_ITEMS:
                    result.records.append(await self._ui_record(
                        rec, await self._ord_of(slot_id), day, my_nick,
                        media_id))
            await self.db.commit()
        await self._after_write(person_id, my_nick, dom_count, head_sig,
                                tail_sig, bootstrapped=True,
                                head_any=head_any, tail_any=tail_any)
        person = await self.get_person_by_id(person_id)
        result.total = int(person["message_count"]) if person else 0
        result.last_ord = await self._last_ord(person_id)
        result.first_ord = 1
        return result

