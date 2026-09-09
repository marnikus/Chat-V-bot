"""Undo + query — world undo + page (<150)."""
import json, logging
from datetime import datetime
log = logging.getLogger("chatbot")
class HistoryUndoQueryMixin:
    async def load_world_undo(self) -> list[dict]:
        if not self.db.is_open: return []
        try: rows = await self.db.fetchall("SELECT seq, kind, value FROM undo_history ORDER BY seq")
        except Exception as exc: log.warning("undo load from %s failed: %s", self.db.path, exc); return []
        out = []
        for seq, kind, value in rows:
            try: out.append({"seq": int(seq), "kind": str(kind), "value": json.loads(str(value))})
            except (TypeError, ValueError): continue
        return out
    async def save_world_undo(self, entries: list[dict]) -> None:
        if not self.db.is_open: return
        try:
            await self.db.execute("DELETE FROM undo_history")
            for e in entries or []:
                if not isinstance(e, dict) or not isinstance(e.get("seq"), int): continue
                await self.db.execute("INSERT OR IGNORE INTO undo_history(seq, kind, value, created_at) VALUES(?,?,?,?)", (int(e["seq"]), str(e.get("kind") or ""), json.dumps(e.get("value"), ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
            await self.db.execute("DELETE FROM sqlite_sequence WHERE name='undo_history'"); await self.db.commit()
        except Exception as exc: log.warning("undo save to %s failed: %s", self.db.path, exc)
    async def page(self, nick: str, **kwargs) -> dict:
        payload = await self.query.page(nick, **kwargs); payload["stats"] = await self.query.person_stats(nick); payload["my_nick"] = self.my_nick; return payload
    def preview_settings(self) -> dict: return dict(self._settings.get("preview") or {})
    def to_json(self) -> str: return json.dumps(self.settings(), ensure_ascii=False)
