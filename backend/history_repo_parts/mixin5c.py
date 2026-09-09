"""History repo 5c loop (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional
log = logging.getLogger("chatbot")
class HistoryRepoMixin5c:
    async def _recover_loop(self, person_id, rows, by_key, media, nick, marker, stamp, requeue_failed):
        known_keys: Optional[set] = None
        used: dict = {}; repaired = requeued = 0; touched = []
        for row in rows:
            mid = row.get("media_id")
            key = self._media_key(row.get("direction"), row.get("from_nick"), row.get("ts_display"))
            matches = by_key.get(key, [])
            at = used.get(key, 0)
            match = matches[at] if at < len(matches) else None
            if at < len(matches): used[key] = at + 1
            if match:
                url = match.media_url; kind = match.media_kind or match.kind; day = str(row.get("day") or "")[:10]
                if mid:
                    existing = await media.get(mid) if mid else None
                    if existing and existing.get("url") == url:
                        if await media.requeue(mid, "backfill_recovery"): requeued += 1
                        await self.db.execute("UPDATE messages SET media_scan_at=?, media_recovered_at=? WHERE id=?", (marker, stamp, int(row["id"])))
                    else:
                        new_mid = await media.register(url, kind, nick=nick, day=day)
                        if new_mid:
                            if await media.requeue(new_mid, "backfill_recovery"): requeued += 1
                            await self.db.execute("UPDATE messages SET media_id=?, kind=?, media_scan_at=?, media_recovered_at=? WHERE id=?", (new_mid, kind, marker, stamp, int(row["id"])))
                            repaired += 1
                else:
                    if known_keys is None: known_keys = await self._all_person_keys(person_id)
                    if match.dup_key in known_keys:
                        await self.db.execute("DELETE FROM messages WHERE id=? AND text='' AND media_id IS NULL", (int(row["id"]),))
                    else:
                        new_mid = await media.register(url, kind, nick=nick, day=day)
                        if new_mid:
                            if await media.requeue(new_mid, "backfill_recovery"): requeued += 1
                            await self.db.execute("UPDATE messages SET media_id=?, kind=?, text=?, text_lc=?, dup_key=?, fp=?, media_scan_at=?, media_recovered_at=? WHERE id=?", (new_mid, kind, match.text, (match.text or "").lower(), match.dup_key, match.ensure_fp(), marker, stamp, int(row["id"])))
                            repaired += 1
            elif mid:
                existing = await media.get(mid) if mid else None
                if existing and existing.get("url"):
                    if requeue_failed and await media.requeue(mid, "backfill_recovery"): requeued += 1
                if existing:
                    await self.db.execute("UPDATE messages SET media_scan_at=? WHERE id=?", (marker, int(row["id"])))
            else:
                await self.db.execute("UPDATE messages SET media_scan_at=? WHERE id=?", (marker, int(row["id"])))
            touched.append(int(row["id"]))
        if touched:
            await self.db.commit(); await self._recount(person_id)
        return {"repaired": repaired, "requeued": requeued, "scanned": len(touched)}
