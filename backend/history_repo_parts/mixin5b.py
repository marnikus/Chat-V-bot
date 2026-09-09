"""History repo 5b recover (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional
log = logging.getLogger("chatbot")
class HistoryRepoMixin5b:
    async def recover_media(self, person_id: int, records, media=None, nick: str = "", now=None, requeue_failed: bool = True) -> dict:
        empty: dict = {"repaired": 0, "requeued": 0, "scanned": 0}
        if media is None or not person_id: return empty
        person_id = int(person_id)
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        self._scan_seq += 1
        marker = f"{stamp}.{self._scan_seq}"
        by_key: dict = {}
        for item in (records or []):
            from .helpers import _as_record
            rec = _as_record(item)
            if not rec.media_url: continue
            key = self._media_key(rec.direction, rec.from_nick, rec.ts_display)
            by_key.setdefault(key, []).append(rec)
        failed_filter = (" OR (m.media_id IS NOT NULL AND md.state IN ('failed','skipped'))" if requeue_failed else "")
        rows = await self.db.fetchdicts("SELECT m.id, m.ord, m.direction, m.from_nick, m.kind, m.text, m.ts_display, m.day, m.media_id, m.media_scan_at, m.media_recovered_at, m.dup_key, md.url AS media_url, md.kind AS media_kind, md.state AS media_state FROM messages m LEFT JOIN media md ON md.id = m.media_id WHERE m.person_id=? AND m.deleted_at='' AND (m.media_scan_at='' OR m.media_scan_at<>?) AND ((m.media_id IS NULL AND (m.kind IN ('image','gif') OR m.text=''))" + failed_filter + ") ORDER BY m.ord", (person_id, marker))
        if not rows: return empty
        return await self._recover_loop(person_id, rows, by_key, media, nick, marker, stamp, requeue_failed)
