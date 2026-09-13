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

#: The undo kinds that belong to a *world* — they move with the database,
#: unlike the app-level kinds that stay behind in the config file.
_WORLD_KINDS = {"people", "labels", "archive", "dbconn"}


def _world_entries(raw) -> list[dict] | None:
    """Well-formed undo entries from the legacy config, or None.

    None means "nothing to rehome": either the state is not a non-empty
    list, or none of its entries is a world kind, so the caller must leave
    the config untouched rather than rewrite it.
    """
    if not isinstance(raw, list) or not raw:
        return None
    entries = [item for item in raw if isinstance(item, dict) and isinstance(item.get("kind"), str)]
    if not any(item.get("kind") in _WORLD_KINDS for item in entries):
        return None
    return entries


def _gaze_str(collector, attr: str) -> str:
    """One of the collector's text run counters, as the gaze table stores it."""
    return str(getattr(collector, attr, "") or "")


def _gaze_int(collector, attr: str) -> str:
    """One of the collector's numeric run counters, as gaze stores it."""
    return str(int(getattr(collector, attr, 0) or 0))


def _gaze_rows(collector, nick: str) -> list:
    """The run counters worth remembering when the app closes.

    Module-level (not a method) because `HistoryMutateService` is already at
    the RULE 16 method cap, and this is a pure projection of the collector.
    """
    return [("partner", nick),
            ("added", _gaze_int(collector, "_added")),
            ("total", _gaze_int(collector, "_total")),
            ("last_sync_reason", _gaze_str(collector, "_last_sync_reason")),
            ("last_sync_added", _gaze_int(collector, "_last_sync_added")),
            ("last_sync_count", _gaze_int(collector, "_last_sync_count"))]


def _config_label_state(raw) -> dict | None:
    """The label store a legacy config carries, or None when it carries none.

    A config with neither definitions nor assignments is not a label store;
    importing it would replace a real one with an empty projection.
    """
    if not isinstance(raw, dict):
        return None
    defs = [item for item in (raw.get("defs") or []) if isinstance(item, dict)]
    assign = raw.get("assign") if isinstance(raw.get("assign"), dict) else {}
    if not defs and not assign:
        return None
    return {"defs": defs, "assign": assign,
            "filter": raw.get("filter") or {"include": [], "exclude": []},
            "next_id": int(raw.get("next_id") or 0)}


def _legacy_text(row: dict, key: str, default: str = "") -> str:
    """One legacy column as text, with its canonical default when empty."""
    return str(row.get(key) or default)


def _legacy_flag(row: dict, key: str) -> int:
    """One legacy 0/1 column as an int, tolerating NULL."""
    return int(row.get(key) or 0)


def _legacy_user_params(row: dict) -> tuple:
    """One legacy `users` row as the canonical INSERT tuple.

    The coercion of eleven columns is its own decision, so it lives here
    rather than inline in the insert loop.
    """
    return (_legacy_text(row, "nick"),
            _legacy_text(row, "gender", "unknown"),
            _legacy_flag(row, "registered"), _legacy_flag(row, "anonymous"),
            _legacy_flag(row, "guest"), _legacy_text(row, "first_seen"),
            _legacy_text(row, "last_seen"), _legacy_flag(row, "messaged"),
            _legacy_flag(row, "message_count"), row.get("last_messaged"),
            _legacy_text(row, "notes"))


def _archive_legacy_trio(legacy_path: str) -> None:
    """Rename db + wal + shm next to the new world (timestamped)."""
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        src = legacy_path + suffix
        if os.path.exists(src):
            os.replace(src, legacy_path + f".migrated-{stamp}" + suffix)


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
        nick = _gaze_str(self.collector, "_nick")
        if not nick:
            return
        stamp = datetime.now().isoformat(timespec="seconds")
        try:
            for key, value in _gaze_rows(self.collector, nick):
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

    async def _legacy_user_rows(self, legacy_path: str) -> list[dict]:
        """All rows of the legacy `users` table (RuntimeError on unreadable)."""
        import aiosqlite
        async with aiosqlite.connect(legacy_path) as src:
            src.row_factory = aiosqlite.Row
            try:
                rows = await src.execute("SELECT nick, gender, registered, anonymous, guest, first_seen, last_seen, messaged, message_count, last_messaged, notes FROM users")
                return [dict(row) for row in await rows.fetchall()]
            except Exception as exc:
                raise RuntimeError(f"cannot read {legacy_path}: {exc}")

    async def _insert_legacy_users(self, legacy: list[dict]) -> int:
        """INSERT OR IGNORE every legacy row; return how many landed."""
        inserted = 0
        for row in legacy:
            cur = await self.db.execute(
                "INSERT OR IGNORE INTO users(nick, gender, registered, "
                "anonymous, guest, first_seen, last_seen, messaged, "
                "message_count, last_messaged, notes) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)", _legacy_user_params(row))
            inserted += int(cur.rowcount or 0)
        await self.db.commit()
        return inserted

    async def _merge_legacy_queue(self, legacy_path: str) -> None:
        legacy = await self._legacy_user_rows(legacy_path)
        inserted = await self._insert_legacy_users(legacy)
        _archive_legacy_trio(legacy_path)
        if self.memory is not None:
            await self.memory.switch_db(self.db.path)
        log.info("merged %d/%d queue row(s) from %s into %s", inserted, len(legacy), os.path.basename(legacy_path), os.path.basename(self.db.path))

    async def _import_config_labels(self) -> bool:
        """One-time import of a label store the config file still carries."""
        state = _config_label_state(self.config.get("labels", default=None))
        if state is None:
            return False
        if int(await self.db.scalar("SELECT COUNT(*) FROM labels")):
            return False
        self._labels._memory = copy.deepcopy(state)
        self._labels._dirty = True
        await self._labels.flush_to_db()
        return True

    def _backfill_seqs(self, entries: list[dict]) -> None:
        """Give every entry a seq when none had one (and persist that)."""
        if all(not isinstance(item.get("seq"), int) for item in entries):
            for seq, entry in enumerate(entries, start=1):
                entry["seq"] = seq
            self.config.set_state(undo_history=copy.deepcopy(entries))

    async def _insert_world_entries(self, entries, stamp) -> int:
        """Move the world-scoped undo entries into the database; count them."""
        moved = 0
        for entry in entries:
            if entry.get("kind") not in _WORLD_KINDS:
                continue
            await self.db.execute("INSERT OR IGNORE INTO undo_history(seq, kind, value, created_at) VALUES(?,?,?,?)", (int(entry.get("seq") or 0), entry["kind"], json.dumps(entry.get("value"), ensure_ascii=False), stamp))
            moved += 1
        await self.db.commit()
        return moved

    async def _rehome_undo_entries(self) -> bool:
        entries = _world_entries(self.config.get_state("undo_history", None))
        if entries is None:
            return False
        self._backfill_seqs(entries)
        moved = await self._insert_world_entries(
            entries, datetime.now().isoformat(timespec="seconds"))
        if moved:
            self.config.set_state(undo_history=[e for e in entries if e.get("kind") not in _WORLD_KINDS])
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
