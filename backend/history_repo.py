"""Write path of the message archive.

Everything that adds to `history.db` goes through here. The two rules that
shape the code:

  * **append-only and idempotent.** Collection re-reads the same DOM over and
    over; replaying a batch, re-running a bootstrap or overlapping a delta
    must never duplicate a line. Identity is the fingerprint plus the
    resolved day, so the same sentence on two days is two rows.
  * **honest about holes.** When the site trimmed its buffer and the new
    batch has nothing in common with what we stored, we append and write a
    `gaps` row rather than pretending the conversation is contiguous.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

from backend.archive_lock import db_operation
from backend.history_db import HistoryDB
from backend.history_models import (MAX_LIVE_ITEMS, Alignment,  # noqa: F401
                                    AppendResult,  # noqa: F401
                                    MessageRecord, fingerprint)  # noqa: F401

log = logging.getLogger("chatbot")
CLEAR_TOKEN_PREFIX = "clear:"

TAIL_FP_LIMIT = 200


# ── alignment ────────────────────────────────────────────────────
def align_batch(batch_fps: Sequence[str],
                tail_fps: Sequence[str]) -> Alignment:
    """Find where `batch_fps` continues the stored conversation.

    Returns the index of the first record after the known tail — the LAST
    place in the batch where our stored suffix occurs, so a conversation
    whose older half was re-rendered above us (the user scrolled up) is not
    mistaken for new messages. When nothing overlaps at all and we do have a
    stored tail, alignment is lost: the caller must append everything and
    record a gap.
    """
    batch = list(batch_fps)
    tail = list(tail_fps)
    if not batch or not tail:
        return Alignment(start=0, matched=True)       # first ever batch
    for end in range(len(batch), 0, -1):
        for k in range(min(len(tail), end), 0, -1):
            if batch[end - k:end] == tail[-k:]:
                return Alignment(start=end, overlap=k, matched=True)
    return Alignment(start=0, gap=True, reason="alignment_lost")


def resolve_days(times: Sequence[str], now: datetime) -> list[str]:
    """Turn HH:MM-only stamps into dates by walking the list BACKWARDS.

    The site shows no date separators, so the newest line is "today" (or
    yesterday if its clock time is still ahead of now) and every step back in
    time that increases the clock crosses midnight.
    """
    day = now.date()
    prev = now.hour * 60 + now.minute
    out: list[str] = []
    for stamp in reversed(list(times)):
        minutes = _minutes(stamp)
        if minutes is None:
            out.append(day.isoformat())
            continue
        if minutes > prev:
            day = day - timedelta(days=1)
        prev = minutes
        out.append(day.isoformat())
    out.reverse()
    return out


def _minutes(stamp: str) -> Optional[int]:
    try:
        hh, mm = str(stamp).strip().split(":")[:2]
        return int(hh) * 60 + int(mm)
    except Exception:                                # noqa: BLE001
        return None


def _as_record(item) -> MessageRecord:
    if isinstance(item, MessageRecord):
        item.ensure_fp()
        return item
    return MessageRecord.from_dict(item)


class HistoryRepo:
    """Append-only writer for one archive database."""

    def __init__(self, db: HistoryDB, media=None, session_id: str = ""):
        self.db = db
        self.media = media
        self.session_id = session_id or ""
        self._scan_seq = 0       # unique scan marker per recovery pass

    # ── persons ──────────────────────────────────────────────────
    @staticmethod
    def normalise_nick(nick: str) -> str:
        return " ".join(str(nick or "").split()).strip()

    @db_operation
    async def ensure_person(self, nick: str) -> int:
        clean = self.normalise_nick(nick)
        if not clean:
            raise ValueError("a person needs a nick")
        row = await self.db.fetchone("SELECT id FROM persons WHERE nick=?",
                                     (clean,))
        if row:
            return int(row[0])
        stamp = datetime.now().isoformat(timespec="seconds")
        cur = await self.db.execute(
            "INSERT INTO persons(nick, nick_lc, first_seen, last_seen, "
            "created_at) VALUES(?,?,?,?,?)",
            (clean, clean.lower(), stamp, stamp, stamp))
        await self.db.commit()
        return int(cur.lastrowid)

    @db_operation
    async def get_person(self, nick: str) -> Optional[dict]:
        row = await self.db.fetchone(
            "SELECT * FROM persons WHERE nick=?", (self.normalise_nick(nick),))
        return self._person_dict(row) if row else None

    @db_operation
    async def get_person_by_id(self, person_id: int) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM persons WHERE id=?",
                                     (person_id,))
        return self._person_dict(row) if row else None

    @staticmethod
    def _person_dict(row) -> dict:
        data = dict(row)
        try:
            data["my_nicks"] = json.loads(data.get("my_nicks") or "[]")
        except Exception:                            # noqa: BLE001
            data["my_nicks"] = []
        data["deleted"] = bool(data.get("deleted_at"))
        return data

    @db_operation
    async def possible_duplicates(self) -> list[dict]:
        """Nicks that differ only by case/spacing — candidates for a merge."""
        rows = await self.db.fetchdicts(
            "SELECT nick_lc, GROUP_CONCAT(nick, char(10)) AS nicks, "
            "COUNT(*) AS n, GROUP_CONCAT(id, ',') AS ids "
            "FROM persons WHERE deleted_at IS NULL "
            "GROUP BY nick_lc HAVING n > 1")
        out = []
        for row in rows:
            out.append({"nick_lc": row["nick_lc"],
                        "nicks": (row["nicks"] or "").split("\n"),
                        "ids": [int(i) for i in (row["ids"] or "").split(",")
                                if i],
                        "count": int(row["n"])})
        return out

    # ── cursor ───────────────────────────────────────────────────
    @db_operation
    async def get_cursor(self, person_id: int) -> dict:
        row = await self.db.fetchone(
            "SELECT * FROM cursors WHERE person_id=?", (person_id,))
        if not row:
            tail = await self.db.fetchall(
                "SELECT fp, dup_key, ord FROM (SELECT fp, dup_key, ord FROM messages "
                "WHERE person_id=? ORDER BY ord DESC LIMIT ?) ORDER BY ord",
                (person_id, TAIL_FP_LIMIT))
            return {"person_id": person_id, "last_ord": int(tail[-1][2]) if tail else 0,
                    "dom_count": 0, "head_sig": "", "tail_sig": "",
                    "tail_fps": [r[0] for r in tail], "tail_keys": [r[1] for r in tail],
                    "bootstrapped": False, "full_scan_complete": False, "full_scan_at": ""}
        data = dict(row)
        try:
            data["tail_fps"] = json.loads(data.get("tail_fps") or "[]")
        except Exception:                            # noqa: BLE001
            data["tail_fps"] = []
        try:
            data["tail_keys"] = json.loads(data.get("tail_keys") or "[]")
        except Exception:                            # noqa: BLE001
            data["tail_keys"] = []
        data["bootstrapped"] = bool(data.get("bootstrapped"))
        data["full_scan_complete"] = bool(data.get("full_scan_complete"))
        return data

    @db_operation
    async def reset_cursor(self, nick: str) -> None:
        """Forget where we were in the DOM — the archive itself is untouched."""
        person_id = await self.ensure_person(nick)
        await self.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, "
            "tail_sig, tail_fps, tail_keys, bootstrapped, "
            "full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,?,0,'','','[]','[]',0,0,'',?) "
            "ON CONFLICT(person_id) DO UPDATE SET dom_count=0, head_sig='', "
            "tail_sig='', tail_fps='[]', tail_keys='[]', bootstrapped=0, "
            "full_scan_complete=0, full_scan_at='', "
            "updated_at=excluded.updated_at",
            (person_id, await self._last_ord(person_id),
             datetime.now().isoformat(timespec="seconds")))
        await self.db.commit()

    async def _last_ord(self, person_id: int) -> int:
        return int(await self.db.scalar(
            "SELECT MAX(ord) FROM messages WHERE person_id=?", (person_id,), 0))

    @db_operation
    async def mark_backfilled(self, nick_or_id) -> None:
        """Record that the full-top-to-bottom scan for this person is done.

        Once set, the passive collector and the incremental `COLLECT_HISTORY`
        block do NOT spend another full history check on that conversation.
        """
        person_id = (int(nick_or_id) if isinstance(nick_or_id, int)
                     else await self.ensure_person(str(nick_or_id)))
        stamp = datetime.now().isoformat(timespec="seconds")
        await self.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, "
            "tail_sig, tail_fps, tail_keys, bootstrapped, "
            "full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,0,0,'','','[]','[]',0,1,?,?) "
            "ON CONFLICT(person_id) DO UPDATE SET full_scan_complete=1, "
            "full_scan_at=excluded.full_scan_at, updated_at=excluded.updated_at",
            (person_id, stamp, stamp))
        await self.db.commit()

    # ── append ───────────────────────────────────────────────────
    @db_operation
    async def append(self, nick: str, records: Iterable, my_nick: str = "",
                     align: bool = True, expect_idx: Optional[int] = None,
                     dom_count: int = 0, head_sig: Optional[str] = None,
                     tail_sig: Optional[str] = None,
                     now: Optional[datetime] = None,
                     session_id: str = "",
                     prepend: bool = False) -> AppendResult:
        now = now or datetime.now()
        person_id = await self.ensure_person(nick)
        recs = [_as_record(r) for r in (records or [])]
        result = AppendResult(person_id=person_id)

        if not recs:
            await self._touch_cursor(person_id, dom_count, head_sig, tail_sig)
            person = await self.get_person_by_id(person_id)
            result.total = int(person["message_count"]) if person else 0
            result.last_ord = await self._last_ord(person_id)
            return result

        repair = await self.recover_text(person_id, recs, now=now)
        result.text_repaired = repair["repaired"]
        if prepend:
            prepended = await self._prepend(person_id, recs, my_nick, now,
                                            dom_count, head_sig, tail_sig,
                                            session_id, nick=nick)
            prepended.text_repaired += result.text_repaired
            return prepended

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
        hidden_slots = await self._deleted_empty_slots(person_id)
        for rec, day in zip(pending, days[start:]):
            dup_key = rec.dup_key
            if dup_key in known or self._was_deleted_slot(rec, day, hidden_slots):
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
                        media_id, message_id=slot_id))
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
                        rec, assigned, day, my_nick, media_id, message_id=cur.lastrowid))
        await self.db.commit()

        await self._after_write(person_id, my_nick, dom_count, head_sig,
                                tail_sig, bootstrapped=True)
        person = await self.get_person_by_id(person_id)
        result.added = added
        result.skipped = len(recs) - added
        result.gap = gap
        result.reason = reason
        result.last_ord = last_ord
        result.total = int(person["message_count"]) if person else 0
        return result

    async def _prepend(self, person_id: int, recs, my_nick: str,
                       now: datetime, dom_count: int,
                       head_sig: Optional[str], tail_sig: Optional[str],
                       session_id: str, nick: str = "") -> AppendResult:
        """Backfill OLDER lines that appeared above what we already stored.

        Their `ord` must come before everything we have, so the existing rows
        are shifted up by however many genuinely new lines we found.
        """
        result = AppendResult(person_id=person_id)
        days = resolve_days([r.ts_display for r in recs], now)
        known = await self._existing_dup_keys(person_id,
                                              [r.dup_key for r in recs])
        fresh = []
        hidden_slots = await self._deleted_empty_slots(person_id)
        for rec, day in zip(recs, days):
            if rec.dup_key in known or self._was_deleted_slot(rec, day, hidden_slots):
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
            # Missing payloads are deferred by the collector. When they
            # arrive, they may belong BETWEEN known lines, not just before
            # the entire archive. Group inserts by their nearest known
            # neighbor, then shift from right to left to keep anchor ords stable.
            anchors = {r["dup_key"]: int(r["ord"]) for r in await self.db.fetchdicts(
                "SELECT dup_key, ord FROM messages WHERE person_id=?", (person_id,))}
            for rec, _day, slot_id, _media_id in fills:
                anchors[rec.dup_key] = await self._ord_of(slot_id)
            positions = {rec.dup_key: i for i, rec in enumerate(recs)}
            groups = {}
            for rec, day in inserts:
                i = positions[rec.dup_key]
                following = next((anchors[r.dup_key] for r in recs[i + 1:]
                                  if r.dup_key in anchors), None)
                preceding = next((anchors[r.dup_key] for r in reversed(recs[:i])
                                  if r.dup_key in anchors), None)
                at = following if following is not None else (
                    preceding + 1 if preceding is not None else 1)
                groups.setdefault(at, []).append((rec, day))
            stamp = datetime.now().isoformat(timespec="seconds")
            for at, group in sorted(groups.items(), reverse=True):
                await self.db.execute(
                    "UPDATE messages SET ord = ord + ? WHERE person_id=? AND ord>=?",
                    (len(group), person_id, at))
                for offset, (rec, day) in enumerate(group):
                    position = at + offset
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
                                rec, position, day, my_nick, media_id, message_id=cur.lastrowid))
            for rec, day, slot_id, media_id in fills:
                await self._fill_slot(slot_id, rec, media_id)
                result.added += 1
                if len(result.records) < MAX_LIVE_ITEMS:
                    result.records.append(await self._ui_record(
                        rec, await self._ord_of(slot_id), day, my_nick,
                        media_id, message_id=slot_id))
            await self.db.commit()
        await self._after_write(person_id, my_nick, dom_count, head_sig,
                                tail_sig, bootstrapped=True)
        person = await self.get_person_by_id(person_id)
        result.total = int(person["message_count"]) if person else 0
        result.last_ord = await self._last_ord(person_id)
        result.first_ord = 1
        return result

    @db_operation
    async def record_gap(self, nick_or_id, after_ord: int, reason: str,
                         detail: str = "") -> None:
        """Note a known hole in a conversation (cap, lost alignment, …)."""
        person_id = (int(nick_or_id) if isinstance(nick_or_id, int)
                     else await self.ensure_person(str(nick_or_id)))
        await self._record_gap(person_id, after_ord, reason, detail)

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
        rows = await self.db.fetchall(
            f"SELECT dup_key FROM messages WHERE person_id=? "
            f"AND dup_key IN ({placeholders})",
            [person_id] + keys)
        return {r[0] for r in rows if r[0]}

    # ── text lost by older parsers / partially rendered DOM ───────
    @db_operation
    async def has_missing_text(self, person_id: int, *, force: bool = False,
                               rescan_after_s: int = 30) -> bool:
        cutoff = (datetime.now() - timedelta(seconds=max(1, rescan_after_s))).isoformat(timespec="seconds")
        return bool(await self.db.scalar(
            "SELECT 1 FROM messages WHERE person_id=? AND deleted_at='' "
            "AND kind='text' AND media_id IS NULL "
            "AND trim(text, char(9)||char(10)||char(13)||' ')='' "
            + ("" if force else "AND (text_scan_at='' OR text_scan_at<?) ") + "LIMIT 1",
            (person_id,) if force else (person_id, cutoff), 0))

    @db_operation
    async def recover_text(self, person_id: int, records, now=None) -> dict:
        """Fill only confidently identified empty text slots (or captions).

        Timestamp alone is not identity: a media line and a text line can
        share one minute. Require the same DOM index, or known neighbors on
        BOTH sides of a shifted slot. Day, author and direction always match.
        Never touch an explicit deletion or replace text already captured.
        """
        recs = [_as_record(r) for r in records or []]
        days = resolve_days([r.ts_display for r in recs], now or datetime.now())
        rows = await self.db.fetchdicts(
            "SELECT m.*, md.url AS media_url FROM messages m "
            "LEFT JOIN media md ON md.id=m.media_id "
            "WHERE m.person_id=? AND m.deleted_at='' "
            "AND trim(m.text, char(9)||char(10)||char(13)||' ')='' "
            "AND (m.kind='text' OR m.media_id IS NOT NULL) ORDER BY m.ord", (person_id,))
        if not rows:
            return {"repaired": 0, "scanned": 0}
        stamp = datetime.now().isoformat(timespec="seconds")
        by_slot = {}
        for pos, (rec, day) in enumerate(zip(recs, days)):
            by_slot.setdefault(self._slot_key(rec) + (day,), []).append((pos, rec))
        repaired, unavailable, used, anchors = 0, 0, set(), None
        for row in rows:
            # Media-only messages legitimately have no text; don't make them
            # automatic text-repair candidates. A caption can still be filled
            # when the same URL actually arrives with text in this batch.
            key = self._slot_row_key(row)
            group = by_slot.get(key, [])
            matches = [(pos, rec) for pos, rec in group
                       if pos not in used and rec.text.strip() and
                       bool(rec.media_url) == bool(row["media_id"]) and
                       (not rec.media_url or rec.media_url == row["media_url"])]
            match = None
            exact = [(pos, rec) for pos, rec in matches if rec.idx == row["dom_idx"]]
            same_position = [r for r in rows if self._slot_row_key(r) == key
                             and r["dom_idx"] == row["dom_idx"]]
            if row["from_nick"] and row["ts_display"] and len(exact) == 1 and len(same_position) == 1:
                match = exact[0]
            elif len(matches) == 1 and len(group) == 1:
                if anchors is None:
                    anchors = {r["dup_key"]: r for r in await self.db.fetchdicts(
                        "SELECT ord, dup_key, day FROM messages WHERE person_id=? "
                        "AND deleted_at='' AND text<>''", (person_id,))}
                pos, rec = matches[0]
                left = next((anchors[r.dup_key] for r in reversed(recs[:pos])
                             if r.dup_key in anchors), None)
                right = next((anchors[r.dup_key] for r in recs[pos + 1:]
                              if r.dup_key in anchors), None)
                if (left and right and left["day"] == right["day"] == row["day"]
                        and left["ord"] < row["ord"] < right["ord"]):
                    match = (pos, rec)
            if match:
                pos, rec = match
                duplicate = await self.db.fetchone(
                    "SELECT id, day, dom_idx, deleted_at FROM messages "
                    "WHERE person_id=? AND dup_key=? AND id<>?",
                    (person_id, rec.dup_key, row["id"]))
                if duplicate:
                    # Only an unmistakable pre-fix duplicate is removed.
                    # Otherwise retain the honest placeholder, not guessed text.
                    if (duplicate["deleted_at"] or duplicate["day"] != row["day"]
                            or duplicate["dom_idx"] != rec.idx):
                        await self.db.execute("UPDATE messages SET text_scan_at=? WHERE id=?", (stamp, row["id"]))
                        unavailable += row["media_id"] is None
                        continue
                    await self.db.execute("DELETE FROM messages WHERE id=?", (duplicate["id"],))
                fp = fingerprint(rec.direction, rec.from_nick, rec.ts_display,
                                 rec.kind, rec.payload, rec.occ)
                await self.db.execute(
                    "UPDATE messages SET text=?, text_lc=?, fp=?, dup_key=?, "
                    "text_scan_at=?, text_recovered_at=? WHERE id=?",
                    (rec.text, rec.text.lower(), fp, rec.dup_key, stamp, stamp, row["id"]))
                used.add(pos)
                repaired += 1
            elif row["media_id"] is None:
                unavailable += 1
                await self.db.execute("UPDATE messages SET text_scan_at=? WHERE id=?", (stamp, row["id"]))
        await self.db.commit()
        if repaired:
            await self._recount(person_id)
            log.info("Recovered text for %d message(s), person_id=%s", repaired, person_id)
        if unavailable:
            log.info("Text not captured for %d stored message(s), person_id=%s: "
                     "payload unavailable or identity ambiguous; Backfill can retry", unavailable, person_id)
        return {"repaired": repaired, "scanned": len(rows)}

    # ── empty slots left by a media line parsed too early ────────
    #
    # The in-page observer can fire before Angular renders `app-chat-image`,
    # so the row is stored with neither text nor media (`kind='text'`,
    # `text=''`, `media_id NULL`). When the real payload arrives — on the
    # next push, the next full read or a backfill — the empty slot must be
    # FILLED, not duplicated (Bug #2, 2026-09-07).

    @staticmethod
    def _slot_key(rec: MessageRecord) -> tuple:
        return (str(rec.direction or "").strip().lower(),
                " ".join(str(rec.from_nick or "").split()).strip().lower(),
                " ".join(str(rec.ts_display or "").split()).strip())

    async def _empty_slot_rows(self, person_id: int) -> list:
        """Every payload-less row of this person, in conversation order.

        Matching happens in Python: SQLite's `lower()` folds ASCII only, so
        a Cyrillic nick like `Хорошо Все` would never equal its own
        lower-cased record key inside a WHERE clause.
        """
        return await self.db.fetchdicts(
            "SELECT id, direction, from_nick, ts_display, day, dom_idx, kind FROM messages "
            "WHERE person_id=? AND deleted_at='' AND media_id IS NULL AND text='' "
            "ORDER BY ord", (person_id,))

    async def _deleted_empty_slots(self, person_id: int) -> list:
        return await self.db.fetchdicts(
            "SELECT direction, from_nick, ts_display, day, dom_idx, kind "
            "FROM messages WHERE person_id=? AND deleted_at<>'' "
            "AND media_id IS NULL AND trim(text, char(9)||char(10)||char(13)||' ')=''",
            (person_id,))

    def _was_deleted_slot(self, rec: MessageRecord, day: str, rows: list) -> bool:
        # Payload-derived fingerprints change when an incomplete body renders.
        # The explicit deletion must survive that change of fingerprint too.
        key = self._slot_key(rec) + (day,)
        return any(self._slot_row_key(row) == key and row["dom_idx"] == rec.idx
                   and (row["kind"] == "text" or bool(rec.media_url)) for row in rows)

    @staticmethod
    def _slot_row_key(row) -> tuple:
        return (str(row.get("direction") or "").strip().lower(),
                " ".join(str(row.get("from_nick") or "").split())
                .strip().lower(),
                " ".join(str(row.get("ts_display") or "").split()).strip(),
                str(row.get("day") or "")[:10])

    async def _take_empty_slot(self, person_id: int, rec: MessageRecord,
                               used: dict, day: str = "",
                               rows: Optional[list] = None) -> Optional[int]:
        """The id of the next payload-less row matching this media line.

        Only media-bearing records use this matching path. Text also renders
        late, but needs the stricter DOM-position/neighbor matching in
        `recover_text`, so a same-minute text cannot steal a media slot. Several media lines can share
        one HH:MM stamp from the same author; slots are consumed in `ord`
        order so the Nth payload-bearing record fills the Nth empty slot.
        The resolved calendar day is part of the key so a NEW message at
        16:24 cannot fill a slot left by yesterday's 16:24.
        """
        if not rec.media_url:
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

    async def _fill_slot(self, slot_id: int, rec: MessageRecord,
                         media_id: Optional[int]) -> None:
        """Upgrade one empty row in place: same line, real payload."""
        await self.db.execute(
            "UPDATE messages SET kind=?, text=?, text_lc=?, media_id=?, "
            "dup_key=?, fp=?, media_recovered_at=? WHERE id=?",
            (rec.kind, rec.text, (rec.text or "").lower(), media_id,
             rec.dup_key, rec.ensure_fp(),
             datetime.now().isoformat(timespec="seconds"), slot_id))

    async def _ord_of(self, row_id: int) -> int:
        return int(await self.db.scalar("SELECT ord FROM messages WHERE id=?",
                                        (row_id,), 0))


    async def _media_id(self, rec: MessageRecord, nick: str = "",
                        day: str = "") -> Optional[int]:
        if not rec.media_url:
            return None
        if self.media is not None:
            # the conversation, not the author: one folder per person holds
            # both directions, which is what makes the tree readable
            return await self.media.register(rec.media_url,
                                             rec.media_kind or rec.kind,
                                             nick=nick, day=day)
        stamp = datetime.now().isoformat(timespec="seconds")
        await self.db.execute(
            "INSERT INTO media(url, kind, state, ref_count, created_at, "
            "last_used) VALUES(?,?,'pending',1,?,?) "
            "ON CONFLICT(url) DO UPDATE SET ref_count=ref_count+1, "
            "last_used=excluded.last_used",
            (rec.media_url, rec.media_kind or rec.kind or "image", stamp,
             stamp))
        row = await self.db.fetchone("SELECT id FROM media WHERE url=?",
                                     (rec.media_url,))
        return int(row[0]) if row else None

    async def _ui_record(self, rec: MessageRecord, ord_value: int, day: str,
                         my_nick: str, media_id, message_id=None) -> dict:
        """The row shape the History window expects, straight from the write.

        The page parser ships `rec` only; the UI needs `ord`, `day`, `time`
        and the joined media fields.  We build those here so the
        `history_appended` signal can deliver only the rows that changed
        instead of re-reading an entire page.
        """
        media = None
        if media_id:
            if self.media is not None:
                row = await self.media.get(media_id)
            else:
                row = await self.db.fetchone("SELECT * FROM media WHERE id=?",
                                             (media_id,))
                row = dict(row) if row else None
            if row:
                media = {
                    "id": int(row.get("id") or media_id),
                    "url": row.get("url") or rec.media_url or "",
                    "kind": row.get("kind") or rec.media_kind or rec.kind,
                    "state": row.get("state") or "pending",
                    "path": row.get("cache_path") or "",
                }
        return {
            "id": message_id,
            "ord": int(ord_value or 0),
            "fp": rec.fp or "",
            "dir": rec.direction or "in",
            "direction": rec.direction or "in",
            "from": rec.from_nick or "",
            "from_nick": rec.from_nick or "",
            "my_nick": my_nick or "",
            "kind": rec.kind or "text",
            "text": rec.text or "",
            "media": media,
            "time": rec.ts_display or "",
            "ts_display": rec.ts_display or "",
            "day": day or "",
            "occ": int(rec.occ or 0),
        }

    async def _record_gap(self, person_id: int, after_ord: int, reason: str,
                          detail: str = "") -> None:
        await self.db.execute(
            "INSERT INTO gaps(person_id, after_ord, reason, detail, created_at)"
            " VALUES(?,?,?,?,?)",
            (person_id, after_ord, reason or "unknown", detail,
             datetime.now().isoformat(timespec="seconds")))
        await self.db.commit()

    # ── media recovery during a backfill ────────────────────────
    @staticmethod
    def _media_key(direction: str, from_nick: str, ts_display: str) -> str:
        return " ".join([
            " ".join(str(direction or "").split()).strip().lower(),
            " ".join(str(from_nick or "").split()).strip().lower(),
            " ".join(str(ts_display or "").split()).strip().lower(),
        ])

    @db_operation
    async def recover_media(self, person_id: int, records, media=None,
                            nick: str = "", now=None,
                            requeue_failed: bool = True) -> dict:
        """Repair images/GIFs whose URL was missing or whose download failed.

        Called while a sync re-reads the DOM. It scans the saved archive for
        messages that *should* have media but are broken, matches them to the
        freshly parsed DOM record (direction + author + the on-screen clock),
        registers the real URL in the right person folder
        (`saved_media/<Latin-nick>/images|gifs/`) and re-queues failed rows so
        the normal downloader retries them.

        Broken shapes (Bug #2 audit, 2026-09-07):

        * ``media_id IS NULL`` and the row is an *empty slot* — kind
          ``image``/``gif`` with no URL, or a ``text`` row with no text
          (a media line parsed before ``app-chat-image`` rendered);
        * ``media_id`` points at a ``failed``/``skipped`` media row.

        With ``requeue_failed=False`` (the cheap automatic pass on ordinary
        ticks) only never-registered rows are repaired — known-bad downloads
        are left for the manual backfill or the "click to restore" marker, so
        a dead URL cannot trigger a download attempt every heartbeat.

        Returns ``{"repaired": n, "requeued": n, "scanned": n}``.
        """
        empty: dict = {"repaired": 0, "requeued": 0, "scanned": 0}
        if media is None or not person_id:
            return empty
        person_id = int(person_id)
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        # Every recovery pass gets a unique marker: the chunked top pass and
        # the newest-window pass of one backfill can run inside the same
        # second, and a shared stamp would make the second pass believe the
        # rows the first pass scanned were its own work.
        self._scan_seq += 1
        marker = f"{datetime.now().isoformat(timespec='seconds')}.{self._scan_seq}"

        # The DOM records from this pass, keyed by the same three visible
        # fields that make a chat line recognisable to a human.
        by_key: dict[str, list[MessageRecord]] = {}
        for item in (records or []):
            rec = _as_record(item)
            if not rec.media_url:
                continue
            key = self._media_key(rec.direction, rec.from_nick, rec.ts_display)
            by_key.setdefault(key, []).append(rec)

        failed_filter = (" OR (m.media_id IS NOT NULL AND "
                         "md.state IN ('failed','skipped'))"
                         if requeue_failed else "")
        rows = await self.db.fetchdicts(
            "SELECT m.id, m.ord, m.direction, m.from_nick, m.kind, m.text, "
            "m.ts_display, m.day, m.media_id, m.media_scan_at, "
            "m.media_recovered_at, m.dup_key, md.url AS media_url, "
            "md.kind AS media_kind, md.state AS media_state "
            "FROM messages m LEFT JOIN media md ON md.id = m.media_id "
            "WHERE m.person_id=? AND m.deleted_at='' "
            "AND (m.media_scan_at='' OR m.media_scan_at<>?) "
            "AND ("
            "  (m.media_id IS NULL AND (m.kind IN ('image','gif') "
            "                           OR m.text=''))"
            + failed_filter +
            ") ORDER BY m.ord",
            (person_id, marker))
        if not rows:
            return empty

        # dup_keys already archived for this person — used to recognise a
        # payload row that already exists next to an empty pre-fix slot.
        # Loaded lazily: only needed when an empty slot finds a DOM match.
        known_keys: Optional[set] = None

        used: dict[str, int] = {}
        repaired = requeued = 0
        touched = []
        for row in rows:
            mid = row.get("media_id")
            key = self._media_key(row.get("direction"), row.get("from_nick"),
                                  row.get("ts_display"))
            matches = by_key.get(key, [])
            at = used.get(key, 0)
            match: Optional[MessageRecord] = None
            if at < len(matches):
                match = matches[at]
                used[key] = at + 1

            if match:
                url = match.media_url
                kind = match.media_kind or match.kind
                day = str(row.get("day") or "")[:10]
                if mid:
                    existing = await media.get(mid) if mid else None
                    if existing and existing.get("url") == url:
                        if await media.requeue(mid, "backfill_recovery"):
                            requeued += 1
                        await self.db.execute(
                            "UPDATE messages SET media_scan_at=?, "
                            "media_recovered_at=? WHERE id=?",
                            (marker, stamp, int(row["id"])))
                    else:
                        new_mid = await media.register(url, kind, nick=nick,
                                                       day=day)
                        if new_mid:
                            if await media.requeue(new_mid,
                                                   "backfill_recovery"):
                                requeued += 1
                            await self.db.execute(
                                "UPDATE messages SET media_id=?, kind=?, "
                                "media_scan_at=?, media_recovered_at=? "
                                "WHERE id=?", (new_mid, kind, marker, stamp,
                                               int(row["id"])))
                            repaired += 1
                else:
                    # an empty slot (or a row that never got its URL): if the
                    # payload-bearing line is already archived elsewhere, the
                    # slot is a pre-fix duplicate artefact — remove it.
                    if known_keys is None:
                        known_keys = await self._all_person_keys(person_id)
                    if match.dup_key in known_keys:
                        await self.db.execute(
                            "DELETE FROM messages WHERE id=? AND text='' "
                            "AND media_id IS NULL", (int(row["id"]),))
                    else:
                        new_mid = await media.register(url, kind, nick=nick,
                                                       day=day)
                        if new_mid:
                            if await media.requeue(new_mid,
                                                   "backfill_recovery"):
                                requeued += 1
                            # rewrite the identity too: the row's old
                            # dup_key has an empty payload, which would let
                            # a later append archive the same line twice
                            await self.db.execute(
                                "UPDATE messages SET media_id=?, kind=?, "
                                "text=?, text_lc=?, dup_key=?, fp=?, "
                                "media_scan_at=?, media_recovered_at=? "
                                "WHERE id=?",
                                (new_mid, kind, match.text,
                                 (match.text or "").lower(), match.dup_key,
                                 match.ensure_fp(), marker, stamp,
                                 int(row["id"])))
                            repaired += 1
            elif mid:
                # We already know the URL (the download failed earlier); the
                # page does not have to be re-read to give it another chance.
                existing = await media.get(mid) if mid else None
                if existing and existing.get("url"):
                    if requeue_failed and \
                            await media.requeue(mid, "backfill_recovery"):
                        requeued += 1
                if existing:
                    await self.db.execute(
                        "UPDATE messages SET media_scan_at=? WHERE id=?",
                        (marker, int(row["id"])))
            else:
                # The DOM pass did not show a URL for this already-saved
                # image/GIF. Remember the scan so we do not search for it
                # endlessly on every backfill.
                await self.db.execute(
                    "UPDATE messages SET media_scan_at=? WHERE id=?",
                    (marker, int(row["id"])))
            touched.append(int(row["id"]))

        if touched:
            await self.db.commit()
            await self._recount(person_id)
        return {"repaired": repaired, "requeued": requeued,
                "scanned": len(touched)}

    async def _all_person_keys(self, person_id: int) -> set:
        rows = await self.db.fetchall(
            "SELECT dup_key FROM messages WHERE person_id=? AND dup_key<>''",
            (person_id,))
        return {r[0] for r in rows}

    @db_operation
    async def has_repairable_media(self, person_id: int,
                                   include_failed: bool = False,
                                   rescan_after_s: int = 600) -> bool:
        """Cheap heartbeat check: is there any media row worth a repair pass?

        ``include_failed`` is True only for the manual backfill (a known-bad
        download gets another chance there, not on every tick). A row the DOM
        could not supply a URL for is skipped for `rescan_after_s` seconds so
        a permanently unrepairable line (e.g. a deleted message) cannot make
        every heartbeat re-read the newest window. The manual backfill
        deliberately ignores that grace period: the top pass of the very
        same sync may have marked a row "scanned, not found" while the row's
        DOM record only returns after the viewport is restored.
        """
        if include_failed:
            clause = ("(media_id IS NULL AND (kind IN ('image','gif') "
                      "OR text='')) OR media_id IN "
                      "(SELECT id FROM media WHERE state IN "
                      "('failed','skipped'))")
            return bool(await self.db.scalar(
                f"SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at='' "
                f"AND ({clause})", (person_id,), 0))
        cutoff = (datetime.now() -
                  timedelta(seconds=max(60, int(rescan_after_s)))
                  ).isoformat(timespec="seconds")
        clause = ("(media_id IS NULL AND (kind IN ('image','gif') "
                  "OR text='') AND (media_scan_at='' OR media_scan_at<?))")
        return bool(await self.db.scalar(
            f"SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at='' AND ({clause})",
            (person_id, cutoff), 0))


    async def _touch_cursor(self, person_id: int, dom_count: int,
                            head_sig: Optional[str],
                            tail_sig: Optional[str]) -> None:
        if not dom_count and head_sig is None and tail_sig is None:
            return
        await self._after_write(person_id, "", dom_count, head_sig, tail_sig,
                                bootstrapped=None)

    async def _after_write(self, person_id: int, my_nick: str, dom_count: int,
                           head_sig: Optional[str], tail_sig: Optional[str],
                           bootstrapped: Optional[bool]) -> None:
        """Refresh counters and the resume cursor.

        `head_sig` / `tail_sig` of None mean "leave as is"; an empty string
        deliberately CLEARS the signature, which is how an interrupted read
        tells the next pass that it may not trust the shortcut.
        """
        await self._recount(person_id, my_nick)
        tail = [r for r in await self.db.fetchall(
            "SELECT fp, dup_key FROM (SELECT fp, dup_key, ord FROM messages "
            "WHERE person_id=? ORDER BY ord DESC LIMIT ?) ORDER BY ord",
            (person_id, TAIL_FP_LIMIT))]
        tail_fps = [r[0] for r in tail]
        tail_keys = [r[1] for r in tail]
        current = await self.get_cursor(person_id)
        flag = current["bootstrapped"] if bootstrapped is None else bootstrapped
        await self.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, "
            "tail_sig, tail_fps, tail_keys, bootstrapped, "
            "full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,0,'',?) "
            "ON CONFLICT(person_id) DO UPDATE SET last_ord=excluded.last_ord, "
            "dom_count=excluded.dom_count, head_sig=excluded.head_sig, "
            "tail_sig=excluded.tail_sig, tail_fps=excluded.tail_fps, "
            "tail_keys=excluded.tail_keys, "
            "bootstrapped=excluded.bootstrapped, updated_at=excluded.updated_at",
            (person_id, await self._last_ord(person_id),
             dom_count or current.get("dom_count") or 0,
             current.get("head_sig", "") if head_sig is None else head_sig,
             current.get("tail_sig", "") if tail_sig is None else tail_sig,
             json.dumps(tail_fps), json.dumps(tail_keys), 1 if flag else 0,
             datetime.now().isoformat(timespec="seconds")))
        await self.db.commit()

    async def _recount(self, person_id: int, my_nick: str = "", *, commit: bool = True) -> None:
        # Counters describe what the user can SEE, so hidden (soft-deleted)
        # rows are excluded — while `last_ord` still spans every row so a
        # deletion can never make the next append reuse an ord.
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS n, "
            "SUM(direction='in') AS ins, SUM(direction='out') AS outs, "
            "SUM(media_id IS NOT NULL) AS media, "
            "MIN(ts_resolved) AS first_ts, MAX(ts_resolved) AS last_ts, "
            "(SELECT MAX(ord) FROM messages WHERE person_id=?) AS last_ord "
            "FROM messages WHERE person_id=? AND deleted_at=''",
            (person_id, person_id))
        person = await self.get_person_by_id(person_id) or {}
        nicks = list(person.get("my_nicks") or [])
        clean = self.normalise_nick(my_nick)
        if clean and clean not in nicks:
            nicks.append(clean)
        await self.db.execute(
            "UPDATE persons SET message_count=?, in_count=?, out_count=?, "
            "media_count=?, last_ord=?, my_nicks=?, "
            "first_seen=COALESCE(?, first_seen), last_seen=COALESCE(?, last_seen) "
            "WHERE id=?",
            (int(row["n"] or 0), int(row["ins"] or 0), int(row["outs"] or 0),
             int(row["media"] or 0), int(row["last_ord"] or 0),
             json.dumps(nicks, ensure_ascii=False),
             row["first_ts"], row["last_ts"], person_id))
        if commit:
            await self.db.commit()

    # ── lifecycle ────────────────────────────────────────────────
    @staticmethod
    def new_op_token() -> str:
        """One stamp shared by every row of a single delete operation.

        Undo is then a single `WHERE deleted_at=?` update, so the history
        entry stays tiny no matter how many messages were hidden.
        """
        return (datetime.now().isoformat(timespec="seconds") + "#" +
                uuid.uuid4().hex[:8])

    @db_operation
    async def soft_delete_message(self, nick: str, message_id: int,
                                  token: str = "") -> str:
        """Hide ONE message. Returns the token that reverses it ('' = no-op)."""
        person = await self.get_person(nick)
        if not person:
            return ""
        stamp = token or self.new_op_token()
        cur = await self.db.execute(
            "UPDATE messages SET deleted_at=? "
            "WHERE id=? AND person_id=? AND deleted_at=''",
            (stamp, int(message_id), int(person["id"])))
        if not cur.rowcount:
            await self.db.commit()
            return ""
        await self.db.commit()
        await self._recount(int(person["id"]))
        return stamp

    @db_operation
    async def legacy_hide_history(self, nick: str, token: str = "") -> str:
        """Pre-reset compatibility only. Never used by Clear or its redo."""
        person = await self.get_person(nick)
        if not person:
            return ""
        stamp = token or CLEAR_TOKEN_PREFIX + self.new_op_token()
        cur = await self.db.execute(
            "UPDATE messages SET deleted_at=? WHERE person_id=? AND deleted_at=''",
            (stamp, int(person["id"])))
        hidden = int(cur.rowcount or 0)
        await self.db.commit()
        if not hidden:
            return ""
        await self._recount(int(person["id"]))
        return stamp

    @db_operation
    async def forget_messages(self, nick: str, *, delete_person: bool = False,
                              message_ids=None, commit: bool = True) -> dict:
        """Erase active message knowledge. Undo is owned by the service, not us.

        Full reset includes hidden rows, every hash/index entry, browser cursor,
        history gaps and recovery markers. `message_ids` is used only for legacy
        maintenance/undo compatibility; it never consults an undo database.
        """
        person = await self.get_person(nick)
        if not person:
            return {"changed": False, "removed": 0, "orphan_files": []}
        pid = int(person["id"])
        partial = message_ids is not None
        ids = sorted({int(i) for i in message_ids or [] if int(i) > 0})
        if partial and not ids:
            return {"changed": False, "removed": 0, "orphan_files": []}
        media_ids, removed = set(), 0
        batches = [None] if not partial else [ids[i:i + 400] for i in range(0, len(ids), 400)]
        for batch in batches:
            where, args = "person_id=?", [pid]
            if batch is not None:
                where += " AND id IN (" + ",".join("?" for _ in batch) + ")"
                args.extend(batch)
            media_ids.update(int(r[0]) for r in await self.db.fetchall(
                "SELECT DISTINCT media_id FROM messages WHERE " + where + " AND media_id IS NOT NULL", args))
            cur = await self.db.execute("DELETE FROM messages WHERE " + where, args)
            removed += int(cur.rowcount or 0)
        tracking = int(await self.db.scalar("SELECT COUNT(*) FROM cursors WHERE person_id=?", (pid,), 0))
        tracking += int(await self.db.scalar("SELECT COUNT(*) FROM gaps WHERE person_id=?", (pid,), 0))
        await self.db.execute("DELETE FROM cursors WHERE person_id=?", (pid,))
        await self.db.execute("DELETE FROM gaps WHERE person_id=?", (pid,))
        orphan_files = []
        for mid in media_ids:
            refs = int(await self.db.scalar("SELECT COUNT(*) FROM messages WHERE media_id=?", (mid,), 0))
            if refs:
                await self.db.execute(
                    "UPDATE media SET ref_count=?, owner=CASE WHEN owner=? THEN "
                    "COALESCE((SELECT p.nick FROM messages m JOIN persons p ON p.id=m.person_id "
                    "WHERE m.media_id=? LIMIT 1),owner) ELSE owner END WHERE id=?",
                    (refs, person["nick"], mid, mid))
            else:
                path = await self.db.scalar("SELECT cache_path FROM media WHERE id=?", (mid,), "")
                await self.db.execute("DELETE FROM media WHERE id=?", (mid,))
                if path and not await self.db.scalar("SELECT 1 FROM media WHERE cache_path=? LIMIT 1", (path,), 0):
                    orphan_files.append(path)
        changed = bool(removed or tracking or delete_person or person.get("message_count") or
                       person.get("last_ord") or person.get("first_seen") or person.get("last_seen") or
                       person.get("my_nicks") or person.get("deleted"))
        if delete_person:
            await self.db.execute("DELETE FROM persons WHERE id=?", (pid,))
        else:
            await self.db.execute(
                "UPDATE persons SET message_count=0,in_count=0,out_count=0,media_count=0,"
                "last_ord=0,first_seen=NULL,last_seen=NULL,my_nicks='[]',deleted_at=NULL WHERE id=?", (pid,))
            if partial:
                # Surviving post-clear rows are current data, not old tombstones.
                rows = await self.db.fetchall("SELECT id FROM messages WHERE person_id=? ORDER BY ord,id", (pid,))
                for ordinal, (rid,) in enumerate(rows, 1):
                    await self.db.execute("UPDATE messages SET ord=? WHERE id=?", (ordinal, rid))
                await self._recount(pid, commit=False)
        if commit:
            await self.db.commit()
        return {"changed": changed, "removed": removed, "orphan_files": list(dict.fromkeys(orphan_files))}

    @db_operation
    async def clear_history(self, nick: str) -> bool:
        return bool((await self.forget_messages(nick))["changed"])

    @db_operation
    async def soft_delete_history(self, nick: str, token: str = "") -> str:
        """Deprecated bulk API: even old callers now get a physical clean slate.

        The returned token is a compatibility receipt only; it is not stored
        in messages and cannot suppress re-collection. UI undo uses snapshots.
        """
        changed = await self.clear_history(nick)
        return (token or self.new_op_token()) if changed else ""

    @staticmethod
    def _clear_filter(legacy_tokens=()) -> tuple[str, list]:
        tokens = list(dict.fromkeys(t for t in legacy_tokens if isinstance(t, str) and t))[:200]
        clause, params = "m.deleted_at LIKE ?", [CLEAR_TOKEN_PREFIX + "%"]
        if tokens:
            clause += " OR m.deleted_at IN (" + ",".join("?" for _ in tokens) + ")"
            params.extend(tokens)
        return clause, params

    @db_operation
    async def cleared_groups(self, nick: str, legacy_tokens=()) -> list[dict]:
        """Recoverable Clear rows, not individual deletes or deleted people.

        New operations have a purpose prefix. Old unprefixed Clear tokens
        must be supplied by the owning global undo history, never guessed.
        The compact result contains IDs/tokens only, no message bodies.
        """
        person = await self.get_person(nick)
        if not person or person.get("deleted"):
            return []
        clause, params = self._clear_filter(legacy_tokens)
        rows = await self.db.fetchall(
            "SELECT m.id, m.deleted_at FROM messages m WHERE m.person_id=? AND (" + clause + ") ORDER BY m.id",
            [int(person["id"])] + params)
        groups = {}
        for rid, token in rows:
            groups.setdefault(token, []).append(int(rid))
        return [{"token": token, "ids": ids} for token, ids in groups.items()]

    @db_operation
    async def cleared_count(self, nick: str, legacy_tokens=()) -> int:
        # Stats must not materialize every cleared row/ID on every UI refresh.
        clause, params = self._clear_filter(legacy_tokens)
        return int(await self.db.scalar(
            "SELECT COUNT(*) FROM messages m JOIN persons p ON p.id=m.person_id "
            "WHERE p.nick=? AND COALESCE(p.deleted_at,'')='' AND (" + clause + ")",
            [self.normalise_nick(nick)] + params, 0))

    @db_operation
    async def apply_clear_restore(self, nick: str, groups, *, forward: bool = True) -> int:
        """Apply/reverse one explicit restoration; later messages are untouched."""
        person = await self.get_person(nick)
        if not person or person.get("deleted"):
            return 0
        changed = 0
        for group in groups or []:
            token = str(group.get("token") or "")
            if not token:
                raise ValueError("A restore group must name its original clear token")
            ids = list(dict.fromkeys(int(i) for i in group.get("ids", []) if int(i) > 0))
            for at in range(0, len(ids), 400):
                batch = ids[at:at + 400]
                current, desired = (token, "") if forward else ("", token)
                cur = await self.db.execute(
                    "UPDATE messages SET deleted_at=? WHERE person_id=? AND deleted_at=? "
                    "AND id IN (" + ",".join("?" for _ in batch) + ")",
                    [desired, int(person["id"]), current] + batch)
                changed += int(cur.rowcount or 0)
        if changed:
            # _recount commits. Keep the visibility update and its counters
            # in the same transaction so a failed restore remains reversible.
            await self._recount(int(person["id"]))
        else:
            await self.db.commit()
        return changed

    @db_operation
    async def restore_cleared(self, nick: str, legacy_tokens=()) -> dict:
        groups = await self.cleared_groups(nick, legacy_tokens)
        restored = await self.apply_clear_restore(nick, groups)
        return {"restored": restored, "groups": groups}

    @db_operation
    async def restore_deleted(self, nick: str, token: str) -> int:
        """Exact reversal of one delete operation. Returns rows restored."""
        person = await self.get_person(nick)
        if not person or not token:
            return 0
        cur = await self.db.execute(
            "UPDATE messages SET deleted_at='' WHERE person_id=? AND deleted_at=?",
            (int(person["id"]), str(token)))
        restored = int(cur.rowcount or 0)
        await self.db.commit()
        if restored:
            await self._recount(int(person["id"]))
        return restored

    @db_operation
    async def deleted_count(self, nick: str = "") -> int:
        if nick:
            person = await self.get_person(nick)
            if not person:
                return 0
            return int(await self.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE person_id=? AND "
                "deleted_at<>''", (int(person["id"]),), 0))
        return int(await self.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE deleted_at<>''", (), 0))

    @db_operation
    async def purge_deleted(self, nick: str = "") -> int:
        """Erase hidden rows for good — the ONLY path that removes bytes."""
        params: tuple = ()
        sql = "DELETE FROM messages WHERE deleted_at<>''"
        person = None
        if nick:
            person = await self.get_person(nick)
            if not person:
                return 0
            sql += " AND person_id=?"
            params = (int(person["id"]),)
        before = await self.deleted_count(nick)
        await self.db.execute(sql, params)
        await self.db.commit()
        if person:
            await self._recount(int(person["id"]))
        return before

    @db_operation
    async def legacy_hide_person(self, nick: str, hard: bool = False,
                                 token: str = "") -> bool:
        """Remove a person WITH their history.

        Soft (the default) tombstones the person and hides every message
        under one token, so a single Ctrl+Z brings both halves back. `hard`
        erases the rows — used only by an explicit purge.
        """
        person = await self.get_person(nick)
        if not person:
            return False
        pid = int(person["id"])
        if hard:
            await self.db.execute("DELETE FROM messages WHERE person_id=?", (pid,))
            await self.db.execute("DELETE FROM cursors WHERE person_id=?", (pid,))
            await self.db.execute("DELETE FROM gaps WHERE person_id=?", (pid,))
            await self.db.execute("DELETE FROM persons WHERE id=?", (pid,))
        else:
            stamp = token or self.new_op_token()
            await self.db.execute(
                "UPDATE messages SET deleted_at=? WHERE person_id=? AND "
                "deleted_at=''", (stamp, pid))
            await self.db.execute(
                "UPDATE persons SET deleted_at=? WHERE id=?", (stamp, pid))
        await self.db.commit()
        if not hard:
            await self._recount(pid)
        return True

    @db_operation
    async def delete_person(self, nick: str, hard: bool = False, token: str = "") -> bool:
        """Delete the actual person and all message state, never a deny tombstone.

        `hard`/`token` remain accepted for older callers. The command service
        decides whether to save an isolated undo snapshot before this call.
        """
        return bool((await self.forget_messages(nick, delete_person=True))["changed"])

    @db_operation
    async def restore_person(self, nick: str, token: str = "") -> bool:
        person = await self.get_person(nick)
        if not person:
            return False
        pid = int(person["id"])
        stamp = token or (person.get("deleted_at") or "")
        if stamp:
            await self.db.execute(
                "UPDATE messages SET deleted_at='' WHERE person_id=? AND "
                "deleted_at=?", (pid, str(stamp)))
        await self.db.execute("UPDATE persons SET deleted_at=NULL WHERE id=?",
                              (pid,))
        await self.db.commit()
        await self._recount(pid)
        return True

    @db_operation
    async def merge_persons(self, from_nick: str, into_nick: str) -> int:
        """Fold one nick's archive into another. Returns the rows moved."""
        source = await self.get_person(from_nick)
        target = await self.get_person(into_nick)
        if not source or not target or source["id"] == target["id"]:
            return 0
        src, dst = int(source["id"]), int(target["id"])
        moved = 0
        rows = await self.db.fetchall(
            "SELECT id FROM messages WHERE person_id=? ORDER BY ord", (src,))
        for row in rows:
            cur = await self.db.execute(
                "UPDATE OR IGNORE messages SET person_id=? WHERE id=?",
                (dst, int(row[0])))
            moved += int(cur.rowcount or 0)
        await self.db.execute("DELETE FROM messages WHERE person_id=?", (src,))
        await self.db.execute("UPDATE gaps SET person_id=? WHERE person_id=?",
                              (dst, src))
        await self.db.execute("DELETE FROM cursors WHERE person_id=?", (src,))
        nicks = list(dict.fromkeys(list(target.get("my_nicks") or []) +
                                   list(source.get("my_nicks") or [])))
        await self.db.execute("UPDATE persons SET my_nicks=? WHERE id=?",
                              (json.dumps(nicks, ensure_ascii=False), dst))
        await self.db.execute("DELETE FROM persons WHERE id=?", (src,))
        await self.db.commit()
        await self._resequence(dst)
        await self._recount(dst)
        return moved

    async def _resequence(self, person_id: int) -> None:
        rows = await self.db.fetchall(
            "SELECT id FROM messages WHERE person_id=? "
            "ORDER BY day, ts_display, ord, id", (person_id,))
        for index, row in enumerate(rows, start=1):
            await self.db.execute("UPDATE messages SET ord=? WHERE id=?",
                                  (index, int(row[0])))
        await self.db.commit()
