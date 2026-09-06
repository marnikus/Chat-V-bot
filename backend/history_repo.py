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
from backend.history_models import (Alignment, AppendResult,  # noqa: F401
                                    MessageRecord, fingerprint)

log = logging.getLogger("chatbot")

TAIL_FP_LIMIT = 200


# ── alignment ────────────────────────────────────────────────────
def align_batch(batch_fps: Sequence[str],
                tail_fps: Sequence[str]) -> Alignment:
    """Find where `batch_fps` continues the stored conversation.

    Returns the index of the first NEW record. When nothing overlaps and we
    do have a stored tail, alignment is lost: the caller must append
    everything and record a gap.
    """
    batch = list(batch_fps)
    tail = list(tail_fps)
    if not batch:
        return Alignment(start=0, matched=True)
    if not tail:
        return Alignment(start=0, matched=True)       # first ever batch
    known = set(tail)
    for k in range(min(len(tail), len(batch)), 0, -1):
        if tail[-k:] == batch[:k]:
            return Alignment(start=k, overlap=k, matched=True)
    # the batch may start *after* our tail (site trimmed the top): if none of
    # its records are known at all, we cannot bridge the hole.
    if any(fp in known for fp in batch):
        # partial, out-of-order overlap — keep the unknown ones, no gap
        first_new = next((i for i, fp in enumerate(batch) if fp not in known),
                         len(batch))
        return Alignment(start=first_new, matched=True, overlap=first_new)
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
        rows = await self.db.fetchall(
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
                    "bootstrapped": False}
        data = dict(row)
        try:
            data["tail_fps"] = json.loads(data.get("tail_fps") or "[]")
        except Exception:                            # noqa: BLE001
            data["tail_fps"] = []
        data["bootstrapped"] = bool(data.get("bootstrapped"))
        return data

    async def reset_cursor(self, nick: str) -> None:
        """Forget where we were in the DOM — the archive itself is untouched."""
        person_id = await self.ensure_person(nick)
        await self.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, "
            "tail_sig, tail_fps, bootstrapped, updated_at) "
            "VALUES(?,?,0,'','','[]',0,?) "
            "ON CONFLICT(person_id) DO UPDATE SET dom_count=0, head_sig='', "
            "tail_sig='', tail_fps='[]', bootstrapped=0, updated_at=excluded.updated_at",
            (person_id, await self._last_ord(person_id),
             datetime.now().isoformat(timespec="seconds")))
        await self.db.commit()

    async def _last_ord(self, person_id: int) -> int:
        return int(await self.db.scalar(
            "SELECT MAX(ord) FROM messages WHERE person_id=?", (person_id,), 0))

    # ── append ───────────────────────────────────────────────────
    async def append(self, nick: str, records: Iterable, my_nick: str = "",
                     align: bool = True, expect_idx: Optional[int] = None,
                     dom_count: int = 0, head_sig: str = "",
                     tail_sig: str = "", now: Optional[datetime] = None,
                     session_id: str = "") -> AppendResult:
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

        cursor = await self.get_cursor(person_id)
        batch_fps = [r.ensure_fp() for r in recs]
        gap, reason, start = False, "", 0
        if align:
            alignment = align_batch(batch_fps, cursor["tail_fps"])
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

        stamp = datetime.now().isoformat(timespec="seconds")
        added = 0
        for rec, day in zip(recs[start:], days[start:]):
            media_id = await self._media_id(rec)
            cur = await self.db.execute(
                "INSERT OR IGNORE INTO messages("
                "person_id, ord, fp, direction, from_nick, my_nick, kind, "
                "text, text_lc, media_id, ts_display, ts_resolved, day, "
                "ts_exact, occ, dom_idx, session_id, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)",
                (person_id, last_ord + 1, rec.fp, rec.direction, rec.from_nick,
                 my_nick or "", rec.kind, rec.text, (rec.text or "").lower(),
                 media_id, rec.ts_display, f"{day} {rec.ts_display or '00:00'}",
                 day, rec.occ, rec.idx, session_id or self.session_id, stamp))
            if cur.rowcount:
                added += 1
                last_ord += 1
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

    async def _media_id(self, rec: MessageRecord) -> Optional[int]:
        if not rec.media_url:
            return None
        if self.media is not None:
            return await self.media.register(rec.media_url,
                                             rec.media_kind or rec.kind)
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

    async def _record_gap(self, person_id: int, after_ord: int, reason: str,
                          detail: str = "") -> None:
        await self.db.execute(
            "INSERT INTO gaps(person_id, after_ord, reason, detail, created_at)"
            " VALUES(?,?,?,?,?)",
            (person_id, after_ord, reason or "unknown", detail,
             datetime.now().isoformat(timespec="seconds")))
        await self.db.commit()

    async def _touch_cursor(self, person_id: int, dom_count: int,
                            head_sig: str, tail_sig: str) -> None:
        if not (dom_count or head_sig or tail_sig):
            return
        await self._after_write(person_id, "", dom_count, head_sig, tail_sig,
                                bootstrapped=None)

    async def _after_write(self, person_id: int, my_nick: str, dom_count: int,
                           head_sig: str, tail_sig: str,
                           bootstrapped: Optional[bool]) -> None:
        await self._recount(person_id, my_nick)
        tail = [r[0] for r in await self.db.fetchall(
            "SELECT fp FROM (SELECT fp, ord FROM messages WHERE person_id=? "
            "ORDER BY ord DESC LIMIT ?) ORDER BY ord",
            (person_id, TAIL_FP_LIMIT))]
        current = await self.get_cursor(person_id)
        flag = current["bootstrapped"] if bootstrapped is None else bootstrapped
        await self.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, "
            "tail_sig, tail_fps, bootstrapped, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(person_id) DO UPDATE SET last_ord=excluded.last_ord, "
            "dom_count=excluded.dom_count, head_sig=excluded.head_sig, "
            "tail_sig=excluded.tail_sig, tail_fps=excluded.tail_fps, "
            "bootstrapped=excluded.bootstrapped, updated_at=excluded.updated_at",
            (person_id, await self._last_ord(person_id),
             dom_count or current.get("dom_count") or 0,
             head_sig or current.get("head_sig") or "",
             tail_sig or current.get("tail_sig") or "",
             json.dumps(tail), 1 if flag else 0,
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
