"""History repo part 1 (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional, Iterable, Sequence

class HistoryRepoMixin1:
    def __init__(self, db: HistoryDB, media=None, session_id: str = ""):
        self.db = db
        self.media = media
        self.session_id = session_id or ""
        self._scan_seq = 0       # unique scan marker per recovery pass

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
        rows = await self.db.fetchdicts(
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

