"""History repo 2b cursor (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional

class HistoryRepoMixin2b:
    async def get_cursor(self, person_id: int) -> dict:
        row = await self.db.fetchone(
            "SELECT * FROM cursors WHERE person_id=?", (person_id,))
        if not row:
            return {"person_id": person_id, "last_ord": 0, "dom_count": 0,
                    "head_sig": "", "tail_sig": "", "head_any": "",
                    "tail_any": "", "tail_fps": [],
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
            "tail_sig, head_any, tail_any, tail_fps, tail_keys, "
            "bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,?,0,'','','','','[]','[]',0,0,'',?) "
            "ON CONFLICT(person_id) DO UPDATE SET dom_count=0, head_sig='', "
            "tail_sig='', head_any='', tail_any='', tail_fps='[]', "
            "tail_keys='[]', bootstrapped=0, "
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
            "tail_sig, head_any, tail_any, tail_fps, tail_keys, "
            "bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,0,0,'','','','','[]','[]',0,1,?,?) "
            "ON CONFLICT(person_id) DO UPDATE SET full_scan_complete=1, "
            "full_scan_at=excluded.full_scan_at, updated_at=excluded.updated_at",
            (person_id, stamp, stamp))
        await self.db.commit()

    # ── append ───────────────────────────────────────────────────
