"""Who a line belongs to, and how it becomes a row.

The identity half of `stores/history_repo.py`: it creates and looks up the
`persons` row a conversation owns (`ensure_person`, `get_person`), offers the
pairs that look like the same human (`possible_duplicates`) to the merge UI,
and renames a person when the partner changed their nick inside the same pane
(`rename_if_same_conversation`). The batch normalisation the writer needs —
`align_batch`, `resolve_days`, `_as_record`, the UI row shape and the media
registration of one record — lives here too, because all of it answers "this
line, of this person, on this day". A person is identified by the trimmed
nick, exactly as before: `normalise_nick` stays on `HistoryRepo` because
callers use it as a class function.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Sequence

from stores.history_models import (Alignment, MessageRecord, dedupe_key,
                                   fingerprint)

log = logging.getLogger("chatbot")

TAIL_FP_LIMIT = 200

#: (output keys, MessageRecord attribute, default, as_int) — the record-
#: derived half of the UI row shape `_ui_record` builds, in output order.
#: Alias pairs share one attribute so `dir`/`direction`, `from`/`from_nick`
#: and `time`/`ts_display` can never disagree (UI contract).
_UI_HEAD_SPECS = (
    (("fp",), "fp", "", False),
    (("dir", "direction"), "direction", "in", False),
    (("from", "from_nick"), "from_nick", "", False),
)
_UI_BODY_SPECS = (
    (("kind",), "kind", "text", False),
    (("text",), "text", "", False),
)
_UI_TAIL_SPECS = (
    (("time", "ts_display"), "ts_display", "", False),
)


def _record_fields(rec: MessageRecord, specs) -> dict:
    """One ordered group of the UI record: coalesce-empty + int casts."""
    out = {}
    for keys, attr, default, as_int in specs:
        value = getattr(rec, attr) or default
        for key in keys:
            out[key] = int(value) if as_int else value
    return out


def _ui_media_payload(row: dict, media_id, rec: MessageRecord) -> dict:
    """The media block the UI record carries (coalesce-empty fields)."""
    return {
        "id": int(row.get("id") or media_id),
        "url": row.get("url") or rec.media_url or "",
        "kind": row.get("kind") or rec.media_kind or rec.kind,
        "state": row.get("state") or "pending",
        "path": row.get("cache_path") or "",
    }


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


class ConversationIdentity:
    """Who a line belongs to, and how it becomes a row."""

    def __init__(self, owner):
        """`owner` is the `HistoryRepo` this part borrows state from."""
        self._owner = owner

    async def ensure_person(self, nick: str) -> int:
        clean = self._owner.normalise_nick(nick)
        if not clean:
            raise ValueError("a person needs a nick")
        row = await self._owner.db.fetchone("SELECT id FROM persons WHERE nick=?",
                                     (clean,))
        if row:
            return int(row[0])
        stamp = datetime.now().isoformat(timespec="seconds")
        # INSERT OR IGNORE: two overlapping syncs (collector heartbeat vs
        # a manual Collect press) can both pass the SELECT above; the
        # loser of the race re-selects the winner's row instead of
        # crashing on the UNIQUE(nick) constraint.
        await self._owner.db.execute(
            "INSERT OR IGNORE INTO persons(nick, nick_lc, first_seen, "
            "last_seen, created_at) VALUES(?,?,?,?,?)",
            (clean, clean.lower(), stamp, stamp, stamp))
        await self._owner.db.commit()
        row = await self._owner.db.fetchone("SELECT id FROM persons WHERE nick=?",
                                     (clean,))
        return int(row[0])

    async def get_person(self, nick: str) -> Optional[dict]:
        row = await self._owner.db.fetchone(
            "SELECT * FROM persons WHERE nick=?", (self._owner.normalise_nick(nick),))
        return self._owner._person_dict(row) if row else None

    async def get_person_by_id(self, person_id: int) -> Optional[dict]:
        row = await self._owner.db.fetchone("SELECT * FROM persons WHERE id=?",
                                     (person_id,))
        return self._owner._person_dict(row) if row else None

    async def possible_duplicates(self) -> list[dict]:
        """Nicks that differ only by case/spacing — candidates for a merge."""
        rows = await self._owner.db.fetchdicts(
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

    async def _ui_record(self, rec: MessageRecord, ord_value: int, day: str,
                         my_nick: str, media_id) -> dict:
        """The row shape the History window expects, straight from the write.

        The page parser ships `rec` only; the UI needs `ord`, `day`, `time`
        and the joined media fields.  We build those here so the
        `history_appended` signal can deliver only the rows that changed
        instead of re-reading an entire page.
        """
        media = await self._ui_media(media_id, rec) if media_id else None
        item = {"ord": int(ord_value or 0)}
        item.update(_record_fields(rec, _UI_HEAD_SPECS))
        item["my_nick"] = my_nick or ""
        item.update(_record_fields(rec, _UI_BODY_SPECS))
        item["media"] = media
        item.update(_record_fields(rec, _UI_TAIL_SPECS))
        item["day"] = day or ""
        item["occ"] = int(rec.occ or 0)
        return item

    async def _ui_media(self, media_id, rec: MessageRecord):
        """The `media` row joined into a UI record, or None.

        Read through the `MediaStore` when the repo has one and straight from
        the table when it does not — a hand-assembled bridge has no cache,
        only the archive.
        """
        row = await self._read_media_row(media_id)
        if not row:
            return None
        return _ui_media_payload(row, media_id, rec)

    async def _read_media_row(self, media_id):
        """The media row via the MediaStore when present, else the table."""
        if self._owner.media is not None:
            return await self._owner.media.get(media_id)
        row = await self._owner.db.fetchone(
            "SELECT * FROM media WHERE id=?", (media_id,))
        return dict(row) if row else None
    async def _media_id(self, rec: MessageRecord, nick: str = "",
                        day: str = "") -> Optional[int]:
        if not rec.media_url:
            return None
        if self._owner.media is not None:
            # the conversation, not the author: one folder per person holds
            # both directions, which is what makes the tree readable
            return await self._owner.media.register(rec.media_url,
                                             rec.media_kind or rec.kind,
                                             nick=nick, day=day)
        stamp = datetime.now().isoformat(timespec="seconds")
        await self._owner.db.execute(
            "INSERT INTO media(url, kind, state, ref_count, created_at, "
            "last_used) VALUES(?,?,'pending',1,?,?) "
            "ON CONFLICT(url) DO UPDATE SET ref_count=ref_count+1, "
            "last_used=excluded.last_used",
            (rec.media_url, rec.media_kind or rec.kind or "image", stamp,
             stamp))
        row = await self._owner.db.fetchone("SELECT id FROM media WHERE url=?",
                                     (rec.media_url,))
        return int(row[0]) if row else None

    async def rename_if_same_conversation(self, old_nick: str,
                                          new_nick: str, head_sig: str,
                                          tail_sig: str,
                                          head_any: str = "",
                                          tail_any: str = "",
                                          dom_count: int = -1,
                                          pane_same: bool = False) -> bool:
        """Continue the previous person's archive under a changed nick.

        The partner can rename at any moment; the conversation on screen is
        still the same one. When the pane we are about to collect shows the
        same head AND tail the previous partner's cursor ended with — the
        same messages, therefore the same chat under a new title — the
        person row is renamed in place and the history, cursors and counters
        continue. Returns True when the rename happened.

        Two signatures are accepted, because the site may re-render history
        under the new nick (every fingerprint changes): the exact head/tail,
        or the author-agnostic head_any/tail_any (fingerprint without the
        nick). `dom_count` must be unchanged — a rename does not add or
        remove messages. `pane_same` must be True: the in-page agent reports
        whether this is literally the SAME pane element as the previous
        probe — a rename happens inside the open pane, while switching to
        another conversation always swaps the pane. That is what keeps two
        different people with similar content from being merged.
        Deliberately conservative: the new nick must be free (an existing
        person means the user may have two conversations — merging stays a
        manual action).
        """
        if not pane_same:
            return False
        old = await self._owner.get_person(old_nick)
        if not old:
            return False
        clean = self._owner.normalise_nick(new_nick)
        if not clean or clean == old["nick"]:
            return False
        if await self._owner.get_person(clean):
            return False                      # nick already known — not a rename
        pid = int(old["id"])
        cursor = await self._owner.get_cursor(pid)
        if not self._same_conversation(cursor, head_sig, tail_sig, head_any,
                                       tail_any, dom_count):
            return False
        return await self._apply_rename(pid, str(old["nick"]), clean)

    def _same_conversation(self, cursor: dict, head_sig: str, tail_sig: str,
                           head_any: str, tail_any: str,
                           dom_count: int) -> bool:
        """Whether the pane still shows the conversation the cursor ended on.

        Deliberately conservative: the previous sync has to have bootstrapped,
        the visible size must be unchanged, and either the exact head/tail
        signatures or the author-agnostic ones must match.
        """
        if not cursor.get("bootstrapped"):
            return False
        if dom_count >= 0 and int(cursor.get("dom_count") or -1) != dom_count:
            return False
        return (self._exact_match(cursor, head_sig, tail_sig)
                or self._any_match(cursor, head_any, tail_any))

    @staticmethod
    def _exact_match(cursor: dict, head_sig: str, tail_sig: str) -> bool:
        """Author-signed head/tail pair identical to the cursor's."""
        return bool(
            head_sig and tail_sig
            and head_sig == str(cursor.get("head_sig") or "")
            and tail_sig == str(cursor.get("tail_sig") or ""))

    @staticmethod
    def _any_match(cursor: dict, head_any: str, tail_any: str) -> bool:
        """Author-agnostic head/tail match, with the cursor's pair present."""
        return bool(
            head_any and tail_any
            and str(cursor.get("head_any") or "")
            and head_any == str(cursor.get("head_any") or "")
            and tail_any == str(cursor.get("tail_any") or ""))

    async def _apply_rename(self, pid: int, old_nick: str,
                            clean: str) -> bool:
        """Rename the person row in place and re-attribute what it stored."""
        stamp = datetime.now().isoformat(timespec="seconds")
        await self._owner.db.execute(
            "UPDATE persons SET nick=?, nick_lc=?, last_seen=? WHERE id=?",
            (clean, clean.lower(), stamp, pid))
        await self._owner.db.commit()
        moved = await self._reattribute(pid, old_nick, clean)
        log.info("partner “%s” is now “%s” — the same conversation "
                 "continues under the new nick (%d stored line(s) "
                 "re-attributed)", old_nick, clean, moved)
        return True

    async def _reattribute(self, pid: int, old_nick: str, clean: str) -> int:
        """Recompute `dup_key`/`fp` of the stored lines under the new nick.

        The site re-renders the past under the new nick, so the stored lines
        must follow — otherwise the next full read would archive every line a
        second time (identity includes the author). There can be no collision
        because a person with the new nick would have refused the rename.
        """
        rows = await self._owner.db.fetchdicts(
            "SELECT m.id, m.occ, m.kind, m.text, m.ts_display, "
            "md.url AS media_url FROM messages m "
            "LEFT JOIN media md ON md.id = m.media_id "
            "WHERE m.person_id=? AND m.from_nick=?",
            (pid, old_nick))
        for row in rows:
            payload = row.get("media_url") or row.get("text") or ""
            occ = int(row.get("occ") or 0)
            await self._owner.db.execute(
                "UPDATE messages SET from_nick=?, dup_key=?, fp=? WHERE id=?",
                (clean,
                 dedupe_key("in", clean, row.get("ts_display") or "",
                            row.get("kind") or "text", payload),
                 fingerprint("in", clean, row.get("ts_display") or "",
                             row.get("kind") or "text", payload, occ),
                 int(row["id"])))
        if rows:
            await self._owner.db.commit()
        return len(rows)

