"""History repo part 4 (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional, Iterable, Sequence

class HistoryRepoMixin4:
    def _slot_key(rec: MessageRecord) -> tuple:
        return (str(rec.direction or "").strip().lower(),
                " ".join(str(rec.from_nick or "").split()).strip().lower(),
                " ".join(str(rec.ts_display or "").split()).strip())

    async def _empty_slot_rows(self, person_id: int) -> list:
        """Every payload-less row of this person, in conversation order.

        Matching happens in Python: SQLite's `lower()` folds ASCII only, so
        a Cyrillic nick like `Хорошо Все` would never equal its own
        lower-cased record key inside a WHERE clause. Hidden (soft-deleted)
        rows are never filled: an "added" row must be one the user can see
        (Bug 4, 2026-09-08).
        """
        return await self.db.fetchdicts(
            "SELECT id, direction, from_nick, ts_display, day FROM messages "
            "WHERE person_id=? AND deleted_at='' "
            "AND media_id IS NULL AND text='' "
            "ORDER BY ord", (person_id,))

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

