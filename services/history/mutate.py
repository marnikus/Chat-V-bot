from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from datetime import datetime
from functools import partial
from stores.world_lock import retry_locked

from .query import MAX_FILE_MB_DEFAULT, _merge

log = logging.getLogger("chatbot")


class HistoryMutateService:
    def apply_settings(self, patch: dict) -> dict:
        patch = dict(patch or {})
        collector = patch.pop("collector", None)
        self._settings = _merge(self._settings, patch)
        media = self._settings["media"]
        self.media.enabled = bool(media.get("enabled", True))
        self._apply_world_media_dir()
        self.media.max_file_bytes = int(float(media.get("max_file_mb", MAX_FILE_MB_DEFAULT)) * 1024 * 1024)
        self.media.max_cache_bytes = int(float(media.get("max_cache_mb", 200)) * 1024 * 1024)
        if collector:
            self.collector.configure(**collector)
        if self.config is not None:
            self.config.set("history", {k: v for k, v in self._settings.items() if k != "collector"})
            self.config.save()
        self._persist_app_settings()
        return self.settings()

    def set_my_nick(self, nick: str) -> str:
        nick = " ".join(str(nick or "").split()).strip()
        self.collector.configure(my_nick=nick)
        self._persist_app_settings()
        return nick

    def bind_labels(self, store) -> None:
        self._labels = store

    def _persist_app_settings(self) -> None:
        if not self.db.is_open:
            return
        stamp = datetime.now().isoformat(timespec="seconds")
        media = self._settings["media"]
        rows = [("my_nick", json.dumps(self.collector.my_nick or "")),
                ("media_max_file_mb", json.dumps(media.get("max_file_mb", MAX_FILE_MB_DEFAULT))),
                ("media_max_cache_mb", json.dumps(media.get("max_cache_mb", 200))),
                ("preview", json.dumps(self._settings.get("preview") or {}))]
        async def work():
            try:
                for key, value in rows:
                    await self.db.execute("INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (key, value, stamp))
                await self.db.commit()
            except Exception as exc:
                log.debug("persist app settings failed: %s", exc)
        try:
            asyncio.get_running_loop().create_task(work())
        except RuntimeError:
            return

    async def seed_app_settings(self) -> None:
        have = {row["key"] for row in await self.db.fetchdicts("SELECT key FROM app_settings")}
        stamp = datetime.now().isoformat(timespec="seconds")
        media = self._settings.get("media") or {}
        rows = [("my_nick", json.dumps(self.collector.my_nick or "")),
                ("media_max_file_mb", json.dumps(media.get("max_file_mb", MAX_FILE_MB_DEFAULT))),
                ("media_max_cache_mb", json.dumps(media.get("max_cache_mb", 200))),
                ("preview", json.dumps(self._settings.get("preview") or {}))]
        for key, value in rows:
            if key not in have:
                await self.db.execute("INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?)", (key, value, stamp))
        await self.db.commit()

    async def save_gaze(self) -> None:
        if not self.db.is_open:
            return
        nick = str(getattr(self.collector, "_nick", "") or "")
        if not nick:
            return
        stamp = datetime.now().isoformat(timespec="seconds")
        rows = [("partner", nick), ("added", str(int(getattr(self.collector, "_added", 0) or 0))),
                ("total", str(int(getattr(self.collector, "_total", 0) or 0))),
                ("last_sync_reason", str(getattr(self.collector, "_last_sync_reason", "") or "")),
                ("last_sync_added", str(int(getattr(self.collector, "_last_sync_added", 0) or 0))),
                ("last_sync_count", str(int(getattr(self.collector, "_last_sync_count", 0) or 0)))]
        try:
            for key, value in rows:
                await self.db.execute("INSERT INTO gaze_data(key, value, updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (key, value, stamp))
            await self.db.commit()
        except Exception as exc:
            log.debug("gaze save failed: %s", exc)

    async def set_meta_flag(self, key: str) -> None:
        try:
            await self.db.set_meta(key, "1")
            await self.db.commit()
        except Exception as exc:
            log.warning("cannot set migration flag %s: %s", key, exc)

    async def _merge_legacy_queue(self, legacy_path: str) -> None:
        import aiosqlite
        async with aiosqlite.connect(legacy_path) as src:
            src.row_factory = aiosqlite.Row
            try:
                rows = await src.execute("SELECT nick, gender, registered, anonymous, guest, first_seen, last_seen, messaged, message_count, last_messaged, notes FROM users")
                legacy = [dict(row) for row in await rows.fetchall()]
            except Exception as exc:
                raise RuntimeError(f"cannot read {legacy_path}: {exc}")
        inserted = 0
        for row in legacy:
            cur = await self.db.execute("INSERT OR IGNORE INTO users(nick, gender, registered, anonymous, guest, first_seen, last_seen, messaged, message_count, last_messaged, notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (str(row.get("nick") or ""), str(row.get("gender") or "unknown"), int(row.get("registered") or 0), int(row.get("anonymous") or 0), int(row.get("guest") or 0), row.get("first_seen") or "", row.get("last_seen") or "", int(row.get("messaged") or 0), int(row.get("message_count") or 0), row.get("last_messaged"), str(row.get("notes") or "")))
            inserted += int(cur.rowcount or 0)
        await self.db.commit()
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            src = legacy_path + suffix
            if os.path.exists(src):
                os.replace(src, legacy_path + f".migrated-{stamp}" + suffix)
        if self.memory is not None:
            await self.memory.switch_db(self.db.path)
        log.info("merged %d/%d queue row(s) from %s into %s", inserted, len(legacy), os.path.basename(legacy_path), os.path.basename(self.db.path))

    async def _import_config_labels(self) -> bool:
        raw = self.config.get("labels", default=None)
        if not isinstance(raw, dict):
            return False
        defs = [item for item in (raw.get("defs") or []) if isinstance(item, dict)]
        assign = raw.get("assign") if isinstance(raw.get("assign"), dict) else {}
        if not defs and not assign:
            return False
        if int(await self.db.scalar("SELECT COUNT(*) FROM labels")):
            return False
        self._labels._memory = copy.deepcopy({"defs": defs, "assign": assign,
            "filter": raw.get("filter") or {"include": [], "exclude": []},
            "next_id": int(raw.get("next_id") or 0)})
        self._labels._dirty = True
        await self._labels.flush_to_db()
        return True

    async def _rehome_undo_entries(self) -> bool:
        raw = self.config.get_state("undo_history", None)
        if not isinstance(raw, list) or not raw:
            return False
        entries = [item for item in raw if isinstance(item, dict) and isinstance(item.get("kind"), str)]
        world_kinds = {"people", "labels", "archive", "dbconn"}
        if not any(item.get("kind") in world_kinds for item in entries):
            return False
        if all(not isinstance(item.get("seq"), int) for item in entries):
            for seq, entry in enumerate(entries, start=1):
                entry["seq"] = seq
            self.config.set_state(undo_history=copy.deepcopy(entries))
        stamp = datetime.now().isoformat(timespec="seconds")
        moved = 0
        for entry in entries:
            if entry.get("kind") not in world_kinds:
                continue
            await self.db.execute("INSERT OR IGNORE INTO undo_history(seq, kind, value, created_at) VALUES(?,?,?,?)", (int(entry.get("seq") or 0), entry["kind"], json.dumps(entry.get("value"), ensure_ascii=False), stamp))
            moved += 1
        await self.db.commit()
        if moved:
            self.config.set_state(undo_history=[e for e in entries if e.get("kind") not in world_kinds])
        return bool(moved)

    async def save_world_undo(self, entries: list[dict]) -> None:
        """Rewrite the world's timeline in ONE transaction, retrying if locked."""
        if not self.db.is_open:
            return
        try:
            await retry_locked(partial(_write_world_undo, self,
                                       _undo_rows(entries)))
        except Exception as exc:                            # noqa: BLE001
            log.warning("undo save to %s failed: %s", self.db.path, exc)


def _undo_rows(entries: list) -> list[tuple]:
    """The timeline rows to store, stamped once for the whole write."""
    stamp = datetime.now().isoformat(timespec="seconds")
    return [(int(e["seq"]), str(e.get("kind") or ""),
             json.dumps(e.get("value"), ensure_ascii=False), stamp)
            for e in entries or []
            if isinstance(e, dict) and isinstance(e.get("seq"), int)]


async def _write_world_undo(host, rows: list[tuple]) -> None:
    """Rewrite the world's undo history in one transaction."""
    await host.db.execute("DELETE FROM undo_history")
    await host.db.executemany(
        "INSERT OR IGNORE INTO undo_history(seq, kind, value, created_at) "
        "VALUES(?,?,?,?)", rows)
    await host.db.execute(
        "DELETE FROM sqlite_sequence WHERE name='undo_history'")
    await host.db.commit()
