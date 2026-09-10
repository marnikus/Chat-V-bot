"""Label IO — DB / config persistence, extracted from LabelStore (AREA B)."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from datetime import datetime

log = logging.getLogger("chatbot")

FILTER_KEY = "label_filter"

class LabelStoreIO:
    def __init__(self, store):
        self.store = store

    async def load_from_db(self, db) -> dict:
        store = self.store
        from stores._label_defs import DEFAULT_COLOR
        store._db = db
        store._dirty = False
        rows = await db.fetchdicts("SELECT id, name, color, created_at FROM labels ORDER BY rowid")
        defs = [{"id": str(r["id"]), "name": str(r["name"] or ""), "color": str(r["color"] or DEFAULT_COLOR), "created_at": str(r["created_at"] or "")} for r in rows]
        assign: dict[str, list[str]] = {}
        known = {d["id"] for d in defs}
        pairs = await db.fetchall("SELECT nick, label_id FROM label_assigns ORDER BY rowid")
        for nick, label_id in pairs:
            if label_id in known:
                assign.setdefault(str(nick), []).append(str(label_id))
        filter_state = {"include": [], "exclude": []}
        raw_filter = await db.scalar("SELECT value FROM app_settings WHERE key=?", (FILTER_KEY,), "")
        if raw_filter:
            try:
                data = json.loads(str(raw_filter))
                if isinstance(data, dict):
                    filter_state = {"include": [str(i) for i in data.get("include") or []], "exclude": [str(i) for i in data.get("exclude") or []]}
            except (TypeError, ValueError):
                pass
        try:
            next_id = int(await db.scalar("SELECT value FROM schema_meta WHERE key='labels_next_id'", (), 0))
        except (TypeError, ValueError):
            next_id = 0
        store._memory = {"defs": defs, "assign": assign, "filter": filter_state, "next_id": next_id}
        return store._normalized()

    async def flush_to_db(self) -> None:
        store = self.store
        if store._db is None or not store._dirty:
            return
        db = store._db
        data = store._normalized()
        stamp = datetime.now().isoformat(timespec="seconds")
        await db.execute("DELETE FROM labels")
        for label in data["defs"]:
            await db.execute("INSERT INTO labels(id, name, color, created_at) VALUES(?,?,?,?)", (label["id"], label["name"], label["color"], label["created_at"]))
        await db.execute("DELETE FROM label_assigns")
        for nick, ids in data["assign"].items():
            for label_id in ids:
                await db.execute("INSERT OR IGNORE INTO label_assigns(nick, label_id) VALUES(?,?)", (nick, label_id))
        await db.execute("INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (FILTER_KEY, json.dumps(data["filter"]), stamp))
        await db.execute("INSERT INTO schema_meta(key, value) VALUES('labels_next_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(int(data["next_id"])),))
        await db.commit()
        store._dirty = False

    def _schedule_flush(self) -> None:
        store = self.store
        if store._db is None:
            return
        store._dirty = True
        if store._scheduler is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        try:
            store._scheduler(store._guarded_flush())
        except Exception as exc:
            log.warning("cannot schedule label flush: %s", exc)

    async def _guarded_flush(self) -> None:
        try:
            await self.flush_to_db()
        except Exception as exc:
            log.warning("label write-through failed: %s", exc)
