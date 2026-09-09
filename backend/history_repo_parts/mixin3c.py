"""History repo 3c gaps (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional

class HistoryRepoMixin3c:
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
