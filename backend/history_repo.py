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
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

from backend.history_db import HistoryDB
from backend.history_models import (MAX_LIVE_ITEMS, Alignment,  # noqa: F401
                                    AppendResult,  # noqa: F401
                                    MessageRecord, fingerprint)

log = logging.getLogger("chatbot")

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

    # ── persons ──────────────────────────────────────────────────
    @staticmethod
    def normalise_nick(nick: str) -> str:
        return " ".join(str(nick or "").split()).strip()

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

    async def get_person(self, nick: str) -> Optional[dict]:
        row = await self.db.fetchone(
            "SELECT * FROM persons WHERE nick=?", (self.normalise_nick(nick),))
        return self._person_dict(row) if row else None

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
    async def get_cursor(self, person_id: int) -> dict:
        row = await self.db.fetchone(
            "SELECT * FROM cursors WHERE person_id=?", (person_id,))
        if not row:
            return {"person_id": person_id, "last_ord": 0, "dom_count": 0,
                    "head_sig": "", "tail_sig": "", "tail_fps": [],
                    "tail_keys": [], "bootstrapped": False,
                    "full_scan_complete": False, "full_scan_at": ""}
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

        if prepend:
            return await self._prepend(person_id, recs, my_nick, now,
                                       dom_count, head_sig, tail_sig,
                                       session_id, nick=nick)

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
        for rec, day in zip(pending, days[start:]):
            dup_key = rec.dup_key
            if dup_key in known:
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
        for rec, day in zip(recs, days):
            if rec.dup_key in known:
                continue
            known.add(rec.dup_key)
            fresh.append((rec, day))
        result.skipped = len(recs) - len(fresh)
        if fresh:
            shift = len(fresh)
            await self.db.execute(
                "UPDATE messages SET ord = ord + ? WHERE person_id=?",
                (shift, person_id))
            stamp = datetime.now().isoformat(timespec="seconds")
            position = 0
            for rec, day in fresh:
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
            await self.db.commit()
        await self._after_write(person_id, my_nick, dom_count, head_sig,
                                tail_sig, bootstrapped=True)
        person = await self.get_person_by_id(person_id)
        result.total = int(person["message_count"]) if person else 0
        result.last_ord = await self._last_ord(person_id)
        result.first_ord = 1
        return result

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
                         my_nick: str, media_id) -> dict:
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

    async def recover_media(self, person_id: int, records, media=None,
                            nick: str = "", now=None) -> int:
        """Repair images/GIFs whose URL was missing or whose download failed.

        Called while a backfill is re-reading the DOM. It scans the saved
        archive for messages that *should* have media (kind image/gif) but
        either have no `media_id` or point at a failed/skipped row, matches
        them to the freshly parsed DOM record (direction + author + the
        on-screen clock), registers the real URL in the right person folder
        and marks the row so a later pass does not retry it endlessly.

        Returns the number of messages whose media got a fresh life (a new
        link, a re-queue or a confirmed URL).
        """
        if media is None or not person_id:
            return 0
        person_id = int(person_id)
        stamp = (now or datetime.now()).isoformat(timespec="seconds")

        # The DOM records from this backfill pass, keyed by the same three
        # visible fields that make a chat line recognisable to a human.
        by_key: dict[str, list[MessageRecord]] = {}
        for item in (records or []):
            rec = _as_record(item)
            if rec.kind not in ("image", "gif") or not rec.media_url:
                continue
            key = self._media_key(rec.direction, rec.from_nick, rec.ts_display)
            by_key.setdefault(key, []).append(rec)

        rows = await self.db.fetchdicts(
            "SELECT m.id, m.ord, m.direction, m.from_nick, m.kind, m.text, "
            "m.ts_display, m.day, m.media_id, m.media_scan_at, "
            "m.media_recovered_at, md.url AS media_url, md.kind AS media_kind, "
            "md.state AS media_state "
            "FROM messages m LEFT JOIN media md ON md.id = m.media_id "
            "WHERE m.person_id=? AND m.kind IN ('image','gif') "
            "AND (m.media_scan_at='' OR m.media_scan_at<>?) "
            "AND ("
            "  (m.media_id IS NULL AND m.media_scan_at='') "
            "  OR (m.media_id IS NOT NULL AND "
            "      md.state IN ('failed','skipped'))"
            ") ORDER BY m.ord",
            (person_id, stamp))
        if not rows:
            return 0

        used: dict[str, int] = {}
        changed = 0
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
                            changed += 1
                        await self.db.execute(
                            "UPDATE messages SET media_scan_at=?, "
                            "media_recovered_at=? WHERE id=?",
                            (stamp, stamp, int(row["id"])))
                    else:
                        new_mid = await media.register(url, kind, nick=nick,
                                                       day=day)
                        if new_mid:
                            await self.db.execute(
                                "UPDATE messages SET media_id=?, "
                                "media_scan_at=?, media_recovered_at=? "
                                "WHERE id=?", (new_mid, stamp, stamp,
                                               int(row["id"])))
                            changed += 1
                else:
                    new_mid = await media.register(url, kind, nick=nick,
                                                   day=day)
                    if new_mid:
                        await self.db.execute(
                            "UPDATE messages SET media_id=?, "
                            "media_scan_at=?, media_recovered_at=? "
                            "WHERE id=?", (new_mid, stamp, stamp,
                                           int(row["id"])))
                        changed += 1
            elif mid:
                # We already know the URL (the download failed earlier); the
                # page does not have to be re-read to give it another chance.
                existing = await media.get(mid) if mid else None
                if existing and existing.get("url"):
                    if await media.requeue(mid, "backfill_recovery"):
                        changed += 1
                if existing:
                    await self.db.execute(
                        "UPDATE messages SET media_scan_at=? WHERE id=?",
                        (stamp, int(row["id"])))
            else:
                # The DOM pass did not show a URL for this already-saved
                # image/GIF. Remember the scan so we do not search for it
                # endlessly on every backfill.
                await self.db.execute(
                    "UPDATE messages SET media_scan_at=? WHERE id=?",
                    (stamp, int(row["id"])))
            touched.append(int(row["id"]))

        if touched:
            await self.db.commit()
            await self._recount(person_id)
        return changed

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

    async def _recount(self, person_id: int, my_nick: str = "") -> None:
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS n, "
            "SUM(direction='in') AS ins, SUM(direction='out') AS outs, "
            "SUM(media_id IS NOT NULL) AS media, "
            "MIN(ts_resolved) AS first_ts, MAX(ts_resolved) AS last_ts, "
            "MAX(ord) AS last_ord FROM messages WHERE person_id=?",
            (person_id,))
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
        await self.db.commit()

    # ── lifecycle ────────────────────────────────────────────────
    async def delete_person(self, nick: str, hard: bool = False) -> bool:
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
            await self.db.execute(
                "UPDATE persons SET deleted_at=? WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"), pid))
        await self.db.commit()
        return True

    async def restore_person(self, nick: str) -> bool:
        person = await self.get_person(nick)
        if not person:
            return False
        await self.db.execute("UPDATE persons SET deleted_at=NULL WHERE id=?",
                              (int(person["id"]),))
        await self.db.commit()
        return True

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
