"""HistoryRepo media recovery — extracted (AREA B)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

class MediaRecovery:
    def __init__(self, repo):
        self.repo = repo

    @property
    def db(self):
        return self.repo.db

    @staticmethod
    def _media_key(direction: str, from_nick: str, ts_display: str) -> str:
        return " ".join([
            " ".join(str(direction or "").split()).strip().lower(),
            " ".join(str(from_nick or "").split()).strip().lower(),
            " ".join(str(ts_display or "").split()).strip().lower(),
        ])

    async def recover_media(self, person_id: int, records, media=None, nick: str = "", now=None, requeue_failed: bool = True) -> dict:
        from stores.history_repo import _as_record
        empty: dict = {"repaired": 0, "requeued": 0, "scanned": 0}
        if media is None or not person_id:
            return empty
        person_id = int(person_id)
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        self.repo._scan_seq += 1
        marker = f"{stamp}.{self.repo._scan_seq}"
        by_key: dict[str, list] = {}
        for item in (records or []):
            rec = _as_record(item)
            if not rec.media_url:
                continue
            key = self._media_key(rec.direction, rec.from_nick, rec.ts_display)
            by_key.setdefault(key, []).append(rec)
        failed_filter = (" OR (m.media_id IS NOT NULL AND md.state IN ('failed','skipped'))" if requeue_failed else "")
        rows = await self.db.fetchdicts(
            "SELECT m.id, m.ord, m.direction, m.from_nick, m.kind, m.text, m.ts_display, m.day, m.media_id, m.media_scan_at, m.media_recovered_at, m.dup_key, md.url AS media_url, md.kind AS media_kind, md.state AS media_state FROM messages m LEFT JOIN media md ON md.id = m.media_id WHERE m.person_id=? AND m.deleted_at='' AND (m.media_scan_at='' OR m.media_scan_at<>?) AND (  (m.media_id IS NULL AND (m.kind IN ('image','gif') OR m.text=''))" + failed_filter + ") ORDER BY m.ord",
            (person_id, marker))
        if not rows:
            return empty
        known_keys: Optional[set] = None
        used: dict[str, int] = {}
        repaired = requeued = 0
        touched = []
        for row in rows:
            mid = row.get("media_id")
            key = self._media_key(row.get("direction"), row.get("from_nick"), row.get("ts_display"))
            matches = by_key.get(key, [])
            at = used.get(key, 0)
            match = None
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
                        await self.db.execute("UPDATE messages SET media_scan_at=?, media_recovered_at=? WHERE id=?", (marker, stamp, int(row["id"])))
                    else:
                        new_mid = await media.register(url, kind, nick=nick, day=day)
                        if new_mid:
                            if await media.requeue(new_mid, "backfill_recovery"):
                                requeued += 1
                            await self.db.execute("UPDATE messages SET media_id=?, kind=?, media_scan_at=?, media_recovered_at=? WHERE id=?", (new_mid, kind, marker, stamp, int(row["id"])))
                            repaired += 1
                else:
                    if known_keys is None:
                        known_keys = await self._all_person_keys(person_id)
                    if match.dup_key in known_keys:
                        await self.db.execute("DELETE FROM messages WHERE id=? AND text='' AND media_id IS NULL", (int(row["id"]),))
                    else:
                        new_mid = await media.register(url, kind, nick=nick, day=day)
                        if new_mid:
                            if await media.requeue(new_mid, "backfill_recovery"):
                                requeued += 1
                            await self.db.execute("UPDATE messages SET media_id=?, kind=?, text=?, text_lc=?, dup_key=?, fp=?, media_scan_at=?, media_recovered_at=? WHERE id=?",
                                (new_mid, kind, match.text, (match.text or "").lower(), match.dup_key, match.ensure_fp(), marker, stamp, int(row["id"])))
                            repaired += 1
            elif mid:
                existing = await media.get(mid) if mid else None
                if existing and existing.get("url"):
                    if requeue_failed and await media.requeue(mid, "backfill_recovery"):
                        requeued += 1
                if existing:
                    await self.db.execute("UPDATE messages SET media_scan_at=? WHERE id=?", (marker, int(row["id"])))
            else:
                await self.db.execute("UPDATE messages SET media_scan_at=? WHERE id=?", (marker, int(row["id"])))
            touched.append(int(row["id"]))
        if touched:
            await self.db.commit()
            await self.repo._recount(person_id)
        return {"repaired": repaired, "requeued": requeued, "scanned": len(touched)}

    async def _all_person_keys(self, person_id: int) -> set:
        rows = await self.db.fetchall("SELECT dup_key FROM messages WHERE person_id=? AND dup_key<>''", (person_id,))
        return {r[0] for r in rows}

    async def has_repairable_media(self, person_id: int, include_failed: bool = False, rescan_after_s: int = 600) -> bool:
        if include_failed:
            clause = "(media_id IS NULL AND (kind IN ('image','gif') OR text='')) OR media_id IN (SELECT id FROM media WHERE state IN ('failed','skipped'))"
            return bool(await self.db.scalar(f"SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at='' AND ({clause})", (person_id,), 0))
        cutoff = (datetime.now() - timedelta(seconds=max(60, int(rescan_after_s)))).isoformat(timespec="seconds")
        clause = "(media_id IS NULL AND (kind IN ('image','gif') OR text='') AND (media_scan_at='' OR media_scan_at<?))"
        return bool(await self.db.scalar(f"SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at='' AND ({clause})", (person_id, cutoff), 0))
