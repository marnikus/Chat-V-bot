"""HistoryRepo writer — append / slot / media / lifecycle (AREA B)."""

from __future__ import annotations

import copy
import json
import logging
import uuid
from datetime import datetime
from typing import Iterable, Optional, Sequence

from stores.history_models import MessageRecord, AppendResult, MAX_LIVE_ITEMS
from stores.history_db import HistoryDB

log = logging.getLogger("chatbot")

TAIL_FP_LIMIT = 200

def _as_record(item) -> MessageRecord:
    if isinstance(item, MessageRecord):
        item.ensure_fp()
        return item
    return MessageRecord.from_dict(item)

class AppendPlanner:
    def __init__(self, repo):
        self.repo = repo

    @property
    def db(self):
        return self.repo.db

    @property
    def media(self):
        return self.repo.media

    @property
    def session_id(self):
        return self.repo.session_id

    async def append(self, nick: str, records: Iterable, my_nick: str = "", align: bool = True, expect_idx: Optional[int] = None, dom_count: int = 0, head_sig: Optional[str] = None, tail_sig: Optional[str] = None, now: Optional[datetime] = None, session_id: str = "", head_any: Optional[str] = None, tail_any: Optional[str] = None, prepend: bool = False) -> AppendResult:
        from stores._history_repo_alignment import align_batch, resolve_days
        now = now or datetime.now()
        person_id = await self.repo.ensure_person(nick)
        recs = [_as_record(r) for r in (records or [])]
        result = AppendResult(person_id=person_id)
        if not recs:
            await self._touch_cursor(person_id, dom_count, head_sig, tail_sig, head_any, tail_any)
            person = await self.repo.get_person_by_id(person_id)
            result.total = int(person["message_count"]) if person else 0
            result.last_ord = await self.repo._last_ord(person_id)
            return result
        if prepend:
            return await self._prepend(person_id, recs, my_nick, now, dom_count, head_sig, tail_sig, session_id, nick=nick, head_any=head_any, tail_any=tail_any)
        cursor = await self.repo.get_cursor(person_id)
        batch_keys = [r.dup_key for r in recs]
        gap, reason, start = False, "", 0
        if align:
            tail = cursor.get("tail_keys") or cursor.get("tail_fps") or []
            alignment = align_batch(batch_keys, tail)
            start, gap, reason = alignment.start, alignment.gap, alignment.reason
        elif expect_idx is not None and recs[0].idx != expect_idx:
            gap, reason = True, "dom_jump"
        days = resolve_days([r.ts_display for r in recs], now)
        last_ord = await self.repo._last_ord(person_id)
        result.first_ord = last_ord + 1
        if gap:
            await self._record_gap(person_id, last_ord, reason, f"expected idx {expect_idx}, got {recs[0].idx}" if reason == "dom_jump" else "")
        pending = recs[start:]
        known = await self._existing_dup_keys(person_id, [r.dup_key for r in pending])
        stamp = datetime.now().isoformat(timespec="seconds")
        added = 0
        slots: dict = {}
        slot_rows: Optional[list] = None
        for rec, day in zip(pending, days[start:]):
            dup_key = rec.dup_key
            if dup_key in known:
                continue
            if slot_rows is None:
                slot_rows = await self._empty_slot_rows(person_id)
            slot_id = await self._take_empty_slot(person_id, rec, slots, day=day, rows=slot_rows)
            if slot_id is not None:
                media_id = await self._media_id(rec, nick, day)
                await self._fill_slot(slot_id, rec, media_id)
                known.add(dup_key)
                added += 1
                if len(result.records) < MAX_LIVE_ITEMS:
                    result.records.append(await self._ui_record(rec, await self._ord_of(slot_id), day, my_nick, media_id))
                continue
            known.add(dup_key)
            media_id = await self._media_id(rec, nick, day)
            assigned = last_ord + 1
            cur = await self.db.execute(
                "INSERT OR IGNORE INTO messages(person_id, ord, fp, direction, from_nick, my_nick, kind, text, text_lc, media_id, ts_display, ts_resolved, day, ts_exact, occ, dom_idx, session_id, created_at, dup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?)",
                (person_id, assigned, rec.fp, rec.direction, rec.from_nick, my_nick or "", rec.kind, rec.text, (rec.text or "").lower(), media_id, rec.ts_display, f"{day} {rec.ts_display or '00:00'}", day, rec.occ, rec.idx, session_id or self.session_id, stamp, dup_key))
            if cur.rowcount:
                added += 1
                last_ord = assigned
                if len(result.records) < MAX_LIVE_ITEMS:
                    result.records.append(await self._ui_record(rec, assigned, day, my_nick, media_id))
        await self.db.commit()
        await self._after_write(person_id, my_nick, dom_count, head_sig, tail_sig, bootstrapped=True, head_any=head_any, tail_any=tail_any)
        person = await self.repo.get_person_by_id(person_id)
        result.added = added
        result.skipped = len(recs) - added
        result.gap = gap
        result.reason = reason
        result.last_ord = last_ord
        result.total = int(person["message_count"]) if person else 0
        return result

    async def _prepend(self, person_id: int, recs, my_nick: str, now: datetime, dom_count: int, head_sig: Optional[str], tail_sig: Optional[str], session_id: str, nick: str = "", head_any: Optional[str] = None, tail_any: Optional[str] = None) -> AppendResult:
        from stores._history_repo_alignment import resolve_days
        result = AppendResult(person_id=person_id)
        days = resolve_days([r.ts_display for r in recs], now)
        known = await self._existing_dup_keys(person_id, [r.dup_key for r in recs])
        fresh = []
        for rec, day in zip(recs, days):
            if rec.dup_key in known:
                continue
            known.add(rec.dup_key)
            fresh.append((rec, day))
        result.skipped = len(recs) - len(fresh)
        if fresh:
            slots: dict = {}
            slot_rows = await self._empty_slot_rows(person_id)
            fills: list = []
            inserts: list = []
            for rec, day in fresh:
                slot_id = await self._take_empty_slot(person_id, rec, slots, day=day, rows=slot_rows)
                if slot_id is not None:
                    fills.append((rec, day, slot_id, await self._media_id(rec, nick, day)))
                else:
                    inserts.append((rec, day))
            if inserts:
                shift = len(inserts)
                await self.db.execute("UPDATE messages SET ord = ord + ? WHERE person_id=?", (shift, person_id))
            stamp = datetime.now().isoformat(timespec="seconds")
            position = 0
            for rec, day in inserts:
                position += 1
                media_id = await self._media_id(rec, nick, day)
                cur = await self.db.execute(
                    "INSERT OR IGNORE INTO messages(person_id, ord, fp, direction, from_nick, my_nick, kind, text, text_lc, media_id, ts_display, ts_resolved, day, ts_exact, occ, dom_idx, session_id, created_at, dup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?)",
                    (person_id, position, rec.fp, rec.direction, rec.from_nick, my_nick or "", rec.kind, rec.text, (rec.text or "").lower(), media_id, rec.ts_display, f"{day} {rec.ts_display or '00:00'}", day, rec.occ, rec.idx, session_id or self.session_id, stamp, rec.dup_key))
                if cur.rowcount:
                    result.added += 1
                    if len(result.records) < MAX_LIVE_ITEMS:
                        result.records.append(await self._ui_record(rec, position, day, my_nick, media_id))
            for rec, day, slot_id, media_id in fills:
                await self._fill_slot(slot_id, rec, media_id)
                result.added += 1
                if len(result.records) < MAX_LIVE_ITEMS:
                    result.records.append(await self._ui_record(rec, await self._ord_of(slot_id), day, my_nick, media_id))
            await self.db.commit()
        await self._after_write(person_id, my_nick, dom_count, head_sig, tail_sig, bootstrapped=True, head_any=head_any, tail_any=tail_any)
        person = await self.repo.get_person_by_id(person_id)
        result.total = int(person["message_count"]) if person else 0
        result.last_ord = await self.repo._last_ord(person_id)
        result.first_ord = 1
        return result

    async def _existing_dup_keys(self, person_id: int, keys) -> set:
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
        rows = await self.db.fetchall(f"SELECT dup_key FROM messages WHERE person_id=? AND dup_key IN ({placeholders})", [person_id] + keys)
        return {r[0] for r in rows if r[0]}

    @staticmethod
    def _slot_key(rec: MessageRecord) -> tuple:
        return (str(rec.direction or "").strip().lower(), " ".join(str(rec.from_nick or "").split()).strip().lower(), " ".join(str(rec.ts_display or "").split()).strip())

    async def _empty_slot_rows(self, person_id: int) -> list:
        return await self.db.fetchdicts("SELECT id, direction, from_nick, ts_display, day FROM messages WHERE person_id=? AND deleted_at='' AND media_id IS NULL AND text='' ORDER BY ord", (person_id,))

    @staticmethod
    def _slot_row_key(row) -> tuple:
        return (str(row.get("direction") or "").strip().lower(), " ".join(str(row.get("from_nick") or "").split()).strip().lower(), " ".join(str(row.get("ts_display") or "").split()).strip(), str(row.get("day") or "")[:10])

    async def _take_empty_slot(self, person_id: int, rec: MessageRecord, used: dict, day: str = "", rows: Optional[list] = None) -> Optional[int]:
        if not rec.media_url and not (rec.text or "").strip():
            return None
        if rows is None:
            rows = await self._empty_slot_rows(person_id)
        want = self._slot_key(rec) + ((day or "")[:10],)
        for row in rows:
            rid = int(row.get("id") or 0)
            if rid in used:
                continue
            if self._slot_row_key(row) == want:
                used[rid] = True
                return rid
        return None

    async def _fill_slot(self, slot_id: int, rec: MessageRecord, media_id: Optional[int]) -> None:
        await self.db.execute("UPDATE messages SET kind=?, text=?, text_lc=?, media_id=?, dup_key=?, fp=?, media_recovered_at=? WHERE id=?",
            (rec.kind, rec.text, (rec.text or "").lower(), media_id, rec.dup_key, rec.ensure_fp(), datetime.now().isoformat(timespec="seconds"), slot_id))

    async def _ord_of(self, row_id: int) -> int:
        return int(await self.db.scalar("SELECT ord FROM messages WHERE id=?", (row_id,), 0))

    async def _media_id(self, rec: MessageRecord, nick: str = "", day: str = "") -> Optional[int]:
        if not rec.media_url:
            return None
        if self.media is not None:
            return await self.media.register(rec.media_url, rec.media_kind or rec.kind, nick=nick, day=day)
        stamp = datetime.now().isoformat(timespec="seconds")
        await self.db.execute("INSERT INTO media(url, kind, state, ref_count, created_at, last_used) VALUES(?,?,'pending',1,?,?) ON CONFLICT(url) DO UPDATE SET ref_count=ref_count+1, last_used=excluded.last_used", (rec.media_url, rec.media_kind or rec.kind or "image", stamp, stamp))
        row = await self.db.fetchone("SELECT id FROM media WHERE url=?", (rec.media_url,))
        return int(row[0]) if row else None

    async def _ui_record(self, rec: MessageRecord, ord_value: int, day: str, my_nick: str, media_id) -> dict:
        media = None
        if media_id:
            if self.media is not None:
                row = await self.media.get(media_id)
            else:
                row = await self.db.fetchone("SELECT * FROM media WHERE id=?", (media_id,))
                row = dict(row) if row else None
            if row:
                media = {"id": int(row.get("id") or media_id), "url": row.get("url") or rec.media_url or "", "kind": row.get("kind") or rec.media_kind or rec.kind, "state": row.get("state") or "pending", "path": row.get("cache_path") or ""}
        return {"ord": int(ord_value or 0), "fp": rec.fp or "", "dir": rec.direction or "in", "direction": rec.direction or "in", "from": rec.from_nick or "", "from_nick": rec.from_nick or "", "my_nick": my_nick or "", "kind": rec.kind or "text", "text": rec.text or "", "media": media, "time": rec.ts_display or "", "ts_display": rec.ts_display or "", "day": day or "", "occ": int(rec.occ or 0)}

    async def _record_gap(self, person_id: int, after_ord: int, reason: str, detail: str = "") -> None:
        await self.db.execute("INSERT INTO gaps(person_id, after_ord, reason, detail, created_at) VALUES(?,?,?,?,?)", (person_id, after_ord, reason or "unknown", detail, datetime.now().isoformat(timespec="seconds")))
        await self.db.commit()

    async def _touch_cursor(self, person_id: int, dom_count: int, head_sig: Optional[str], tail_sig: Optional[str], head_any: Optional[str] = None, tail_any: Optional[str] = None) -> None:
        if not dom_count and head_sig is None and tail_sig is None:
            return
        await self._after_write(person_id, "", dom_count, head_sig, tail_sig, bootstrapped=None, head_any=head_any, tail_any=tail_any)

    async def _after_write(self, person_id: int, my_nick: str, dom_count: int, head_sig: Optional[str], tail_sig: Optional[str], bootstrapped: Optional[bool], head_any: Optional[str] = None, tail_any: Optional[str] = None) -> None:
        await self._recount(person_id, my_nick)
        tail = [r for r in await self.db.fetchall("SELECT fp, dup_key FROM (SELECT fp, dup_key, ord FROM messages WHERE person_id=? ORDER BY ord DESC LIMIT ?) ORDER BY ord", (person_id, TAIL_FP_LIMIT))]
        tail_fps = [r[0] for r in tail]
        tail_keys = [r[1] for r in tail]
        current = await self.repo.get_cursor(person_id)
        flag = current["bootstrapped"] if bootstrapped is None else bootstrapped
        await self.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, tail_sig, head_any, tail_any, tail_fps, tail_keys, bootstrapped, full_scan_complete, full_scan_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,0,'',?) ON CONFLICT(person_id) DO UPDATE SET last_ord=excluded.last_ord, dom_count=excluded.dom_count, head_sig=excluded.head_sig, tail_sig=excluded.tail_sig, head_any=excluded.head_any, tail_any=excluded.tail_any, tail_fps=excluded.tail_fps, tail_keys=excluded.tail_keys, bootstrapped=excluded.bootstrapped, updated_at=excluded.updated_at",
            (person_id, await self.repo._last_ord(person_id), dom_count or current.get("dom_count") or 0, current.get("head_sig", "") if head_sig is None else head_sig, current.get("tail_sig", "") if tail_sig is None else tail_sig, current.get("head_any", "") if head_any is None else head_any, current.get("tail_any", "") if tail_any is None else tail_any, json.dumps(tail_fps), json.dumps(tail_keys), 1 if flag else 0, datetime.now().isoformat(timespec="seconds")))
        await self.db.commit()

    async def _recount(self, person_id: int, my_nick: str = "") -> None:
        row = await self.db.fetchone("SELECT COUNT(*) AS n, SUM(direction='in') AS ins, SUM(direction='out') AS outs, SUM(media_id IS NOT NULL) AS media, MIN(ts_resolved) AS first_ts, MAX(ts_resolved) AS last_ts, (SELECT MAX(ord) FROM messages WHERE person_id=?) AS last_ord FROM messages WHERE person_id=? AND deleted_at=''", (person_id, person_id))
        person = await self.repo.get_person_by_id(person_id) or {}
        nicks = list(person.get("my_nicks") or [])
        clean = self.repo.normalise_nick(my_nick) if hasattr(self.repo, 'normalise_nick') else " ".join(str(my_nick or "").split()).strip()
        if clean and clean not in nicks:
            nicks.append(clean)
        await self.db.execute("UPDATE persons SET message_count=?, in_count=?, out_count=?, media_count=?, last_ord=?, my_nicks=?, first_seen=COALESCE(?, first_seen), last_seen=COALESCE(?, last_seen) WHERE id=?",
            (int(row["n"] or 0), int(row["ins"] or 0), int(row["outs"] or 0), int(row["media"] or 0), int(row["last_ord"] or 0), json.dumps(nicks, ensure_ascii=False), row["first_ts"], row["last_ts"], person_id))
        await self.db.commit()
