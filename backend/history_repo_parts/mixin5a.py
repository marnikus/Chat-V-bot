"""History repo 5a ui (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional

class HistoryRepoMixin5a:
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

