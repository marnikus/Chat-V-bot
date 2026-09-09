"""World A — legacy queue + labels + undo rehome (<150)."""
import asyncio, copy, json, logging, os, re
from datetime import datetime
log = logging.getLogger("chatbot")
class HistoryWorldAMixin:
    async def _merge_legacy_queue(self, legacy_path: str) -> None:
        import aiosqlite
        async with aiosqlite.connect(legacy_path) as src:
            src.row_factory = aiosqlite.Row
            try:
                rows = await src.execute("SELECT nick, gender, registered, anonymous, guest, first_seen, last_seen, messaged, message_count, last_messaged, notes FROM users")
                legacy = [dict(r) for r in await rows.fetchall()]
            except Exception as exc: raise RuntimeError(f"cannot read {legacy_path}: {exc}")
        inserted = 0
        for row in legacy:
            cur = await self.db.execute("INSERT OR IGNORE INTO users(nick, gender, registered, anonymous, guest, first_seen, last_seen, messaged, message_count, last_messaged, notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (str(row.get("nick") or ""), str(row.get("gender") or "unknown"), int(row.get("registered") or 0), int(row.get("anonymous") or 0), int(row.get("guest") or 0), row.get("first_seen") or "", row.get("last_seen") or "", int(row.get("messaged") or 0), int(row.get("message_count") or 0), row.get("last_messaged"), str(row.get("notes") or "")))
            inserted += int(cur.rowcount or 0)
        await self.db.commit()
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            source = legacy_path + suffix
            if not os.path.exists(source): continue
            os.replace(source, legacy_path + f".migrated-{stamp}" + suffix)
        if self.memory is not None: await self.memory.switch_db(self.db.path)
        log.info("merged %d/%d queue row(s) from %s into %s", inserted, len(legacy), os.path.basename(legacy_path), os.path.basename(self.db.path))
    async def _import_config_labels(self) -> bool:
        raw = self.config.get("labels", default=None)
        if not isinstance(raw, dict): return False
        defs = [d for d in (raw.get("defs") or []) if isinstance(d, dict)]; assign = raw.get("assign") if isinstance(raw.get("assign"), dict) else {}
        if not defs and not assign: return False
        existing = int(await self.db.scalar("SELECT COUNT(*) FROM labels"))
        if existing: return False
        store = self._labels; data = {"defs": defs, "assign": assign, "filter": raw.get("filter") or {"include": [], "exclude": []}, "next_id": int(raw.get("next_id") or 0)}
        store._memory = copy.deepcopy(data); store._dirty = True; await store.flush_to_db(); return True
    async def _rehome_undo_entries(self) -> bool:
        raw = self.config.get_state("undo_history", None)
        if not isinstance(raw, list) or not raw: return False
        entries = [e for e in raw if isinstance(e, dict) and isinstance(e.get("kind"), str)]; world_kinds = ("people", "labels", "archive", "dbconn")
        if not any(e.get("kind") in world_kinds for e in entries): return False
        if all(not isinstance(e.get("seq"), int) for e in entries):
            for pos, entry in enumerate(entries, start=1): entry["seq"] = pos
            self.config.set_state(undo_history=copy.deepcopy(entries))
        moved = 0; stamp = datetime.now().isoformat(timespec="seconds")
        for entry in entries:
            if entry.get("kind") not in world_kinds: continue
            seq = int(entry.get("seq") or 0)
            await self.db.execute("INSERT OR IGNORE INTO undo_history(seq, kind, value, created_at) VALUES(?,?,?,?)", (seq, entry["kind"], json.dumps(entry.get("value"), ensure_ascii=False), stamp)); moved += 1
        await self.db.commit()
        if not moved: return False
        app_entries = [e for e in entries if e.get("kind") not in world_kinds]; self.config.set_state(undo_history=app_entries); return True
