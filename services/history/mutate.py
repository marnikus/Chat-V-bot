from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from datetime import datetime

from .query import MAX_FILE_MB_DEFAULT, _merge

log = logging.getLogger("chatbot")

#: Undo entries that describe the shared world rather than one conversation:
#: they belong in the database, and app.json keeps only the rest.
WORLD_UNDO_KINDS = frozenset({"people", "labels", "archive", "dbconn"})

#: How the undo table is filled, by the rehome import and by every save.
UNDO_INSERT = ("INSERT OR IGNORE INTO undo_history(seq, kind, value, created_at) "
               "VALUES(?,?,?,?)")

#: The legacy queue database's `users` columns, in the order the import binds
#: them, each with how a missing or empty value is read: "str" coerces to text,
#: "text" keeps whatever the row held, "int" counts, "raw" passes it through.
#: One table for the SELECT and the INSERT, so a new column cannot land in one
#: and not the other.
LEGACY_COLUMNS = (
    ("nick", "str", ""), ("gender", "str", "unknown"),
    ("registered", "int", 0), ("anonymous", "int", 0), ("guest", "int", 0),
    ("first_seen", "text", ""), ("last_seen", "text", ""),
    ("messaged", "int", 0), ("message_count", "int", 0),
    ("last_messaged", "raw", None), ("notes", "str", ""),
)
LEGACY_SELECT = ("SELECT " + ", ".join(key for key, _, _ in LEGACY_COLUMNS)
                 + " FROM users")
LEGACY_INSERT = ("INSERT OR IGNORE INTO users("
                 + ", ".join(key for key, _, _ in LEGACY_COLUMNS) + ") VALUES("
                 + ", ".join("?" * len(LEGACY_COLUMNS)) + ")")

#: What the gaze panel tracks: the stored key and the collector attribute.
GAZE_FIELDS = (("partner", "_nick", "text"),
               ("added", "_added", "int"),
               ("total", "_total", "int"),
               ("last_sync_reason", "_last_sync_reason", "text"),
               ("last_sync_added", "_last_sync_added", "int"),
               ("last_sync_count", "_last_sync_count", "int"))
GAZE_UPSERT = ("INSERT INTO gaze_data(key, value, updated_at) VALUES(?,?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
               "updated_at=excluded.updated_at")


_LEGACY_READERS = {
    "str": lambda value, default: str(value or default),
    "text": lambda value, default: value or default,
    "int": lambda value, default: int(value or 0),
    "raw": lambda value, default: value,
}


def _legacy_row(row: dict) -> tuple:
    """One legacy queue row, as our schema wants its values, in column order."""
    return tuple(_LEGACY_READERS[kind](row.get(key), default)
                 for key, kind, default in LEGACY_COLUMNS)


def _gaze_values(collector) -> list:
    """The collector's live gaze numbers, as strings the table can hold."""
    out = []
    for key, attr, kind in GAZE_FIELDS:
        value = getattr(collector, attr, None)
        out.append((key, str(int(value or 0)) if kind == "int" else str(value or "")))
    return out


def _undo_entries(raw) -> list:
    """The well-formed entries of a stored undo history, in order."""
    if not isinstance(raw, list):
        return []
    return [item for item in raw
            if isinstance(item, dict) and isinstance(item.get("kind"), str)]


def _undo_needing_a_number(entries: list) -> bool:
    """True when nothing in the history is numbered yet."""
    return not any(isinstance(item.get("seq"), int) for item in entries)


def _world_undo(entries: list) -> list:
    """The entries that describe the shared world."""
    return [e for e in entries if e["kind"] in WORLD_UNDO_KINDS]


def _app_json_undo(entries: list) -> list:
    """The entries that stay in app.json once the world's have moved."""
    return [e for e in entries if e["kind"] not in WORLD_UNDO_KINDS]


def _config_label_payload(raw: dict) -> dict:
    """The label world as app.json stored it — only what is well-formed."""
    return {
        "defs": [item for item in (raw.get("defs") or []) if isinstance(item, dict)],
        "assign": raw.get("assign") if isinstance(raw.get("assign"), dict) else {},
        "filter": raw.get("filter") or {"include": [], "exclude": []},
        "next_id": int(raw.get("next_id") or 0),
    }


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
        """Store the gaze numbers; no database open, or no nick, means nothing."""
        if not self.db.is_open or not str(getattr(self.collector, "_nick", "") or ""):
            return
        rows = _gaze_values(self.collector)
        stamp = datetime.now().isoformat(timespec="seconds")
        try:
            for key, value in rows:
                await self.db.execute(GAZE_UPSERT, (key, value, stamp))
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
        """Fold the standalone queue database into this world, then retire it."""
        import aiosqlite
        async with aiosqlite.connect(legacy_path) as src:
            src.row_factory = aiosqlite.Row
            try:
                rows = await src.execute(LEGACY_SELECT)
                legacy = [dict(row) for row in await rows.fetchall()]
            except Exception as exc:
                raise RuntimeError(f"cannot read {legacy_path}: {exc}")
        # Every insert is INSERT OR IGNORE and the file rename below happens
        # only after the commit, so a merge that dies halfway can be re-run.
        inserted = 0
        for row in legacy:
            cur = await self.db.execute(LEGACY_INSERT, _legacy_row(row))
            inserted += int(cur.rowcount or 0)
        await self.db.commit()
        self._retire_legacy_files(legacy_path)
        if self.memory is not None:
            await self.memory.switch_db(self.db.path)
        log.info("merged %d/%d queue row(s) from %s into %s", inserted, len(legacy),
                 os.path.basename(legacy_path), os.path.basename(self.db.path))

    @staticmethod
    def _retire_legacy_files(legacy_path: str) -> None:
        """Move the source aside, so the next run cannot merge it a second time."""
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            src = legacy_path + suffix
            if os.path.exists(src):
                os.replace(src, legacy_path + f".migrated-{stamp}" + suffix)

    async def _import_config_labels(self) -> bool:
        """Adopt the labels app.json still holds — once, into an empty world."""
        raw = self.config.get("labels", default=None)
        if not isinstance(raw, dict):
            return False
        payload = _config_label_payload(raw)
        if not payload["defs"] and not payload["assign"]:
            return False
        if int(await self.db.scalar("SELECT COUNT(*) FROM labels")):
            return False
        self._labels._memory = copy.deepcopy(payload)
        self._labels._dirty = True
        await self._labels.flush_to_db()
        return True

    async def _rehome_undo_entries(self) -> bool:
        """Move world-wide undo history out of app.json and into the database."""
        entries = _undo_entries(self.config.get_state("undo_history", None))
        if not _world_undo(entries):
            return False
        # Numbered first and written back first: `seq` is what the table keys on.
        if _undo_needing_a_number(entries):
            for seq, entry in enumerate(entries, start=1):
                entry["seq"] = seq
            self.config.set_state(undo_history=copy.deepcopy(entries))
        stamp = datetime.now().isoformat(timespec="seconds")
        world = _world_undo(entries)
        for entry in world:
            await self.db.execute(UNDO_INSERT, (
                int(entry.get("seq") or 0), entry["kind"],
                json.dumps(entry.get("value"), ensure_ascii=False), stamp))
        await self.db.commit()
        if not world:
            return False
        self.config.set_state(undo_history=_app_json_undo(entries))
        return True

    async def save_world_undo(self, entries: list[dict]) -> None:
        if not self.db.is_open:
            return
        try:
            await self.db.execute("DELETE FROM undo_history")
            for entry in entries or []:
                if isinstance(entry, dict) and isinstance(entry.get("seq"), int):
                    await self.db.execute(UNDO_INSERT, (int(entry["seq"]), str(entry.get("kind") or ""), json.dumps(entry.get("value"), ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
            await self.db.execute("DELETE FROM sqlite_sequence WHERE name='undo_history'")
            await self.db.commit()
        except Exception as exc:
            log.warning("undo save to %s failed: %s", self.db.path, exc)
