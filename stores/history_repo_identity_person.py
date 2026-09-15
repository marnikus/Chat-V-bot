"""Person lifecycle — extracted from history_repo_identity (H-C5 split)

≤100 LOC.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger("chatbot")


class ConversationIdentityPerson:
    def __init__(self, owner):
        self._owner = owner

    async def ensure_person(self, nick: str) -> int:
        clean = self._owner.normalise_nick(nick)
        if not clean:
            raise ValueError("a person needs a nick")
        row = await self._owner.db.fetchone("SELECT id FROM persons WHERE nick=?", (clean,))
        if row:
            return int(row[0])
        stamp = datetime.now().isoformat(timespec="seconds")
        await self._owner.db.execute(
            "INSERT OR IGNORE INTO persons(nick, nick_lc, first_seen, last_seen, created_at) VALUES(?,?,?,?,?)",
            (clean, clean.lower(), stamp, stamp, stamp),
        )
        await self._owner.db.commit()
        row = await self._owner.db.fetchone("SELECT id FROM persons WHERE nick=?", (clean,))
        return int(row[0])

    async def get_person(self, nick: str) -> Optional[dict]:
        row = await self._owner.db.fetchone(
            "SELECT * FROM persons WHERE nick=?", (self._owner.normalise_nick(nick),)
        )
        return self._owner._person_dict(row) if row else None

    async def get_person_by_id(self, person_id: int) -> Optional[dict]:
        row = await self._owner.db.fetchone("SELECT * FROM persons WHERE id=?", (person_id,))
        return self._owner._person_dict(row) if row else None

    async def possible_duplicates(self) -> list[dict]:
        rows = await self._owner.db.fetchdicts(
            "SELECT nick_lc, GROUP_CONCAT(nick, char(10)) AS nicks, COUNT(*) AS n, GROUP_CONCAT(id, ',') AS ids "
            "FROM persons WHERE deleted_at IS NULL GROUP BY nick_lc HAVING n > 1"
        )
        out = []
        for row in rows:
            out.append(
                {
                    "nick_lc": row["nick_lc"],
                    "nicks": (row["nicks"] or "").split("\n"),
                    "ids": [int(i) for i in (row["ids"] or "").split(",") if i],
                    "count": int(row["n"]),
                }
            )
        return out
