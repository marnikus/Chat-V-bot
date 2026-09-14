"""App-settings and gaze persistence (H-C2 split of `mutate.py`).

One operation: keep the *app-level* settings — my nick, the media caps, the
preview flags and the collector's run counters — in the world's
`app_settings` / `gaze_data` tables, so a database carries its own settings
instead of only the global config file.

Mixed into `HistoryService` through `mutate.HistoryMutateService`; the legacy
import lives in `mutate_import.py` and the world undo entries in
`mutate_world.py`.

Import direction: `.query` for the settings defaults and the merge helper; no
stores import (the tables are reached through the host's `self.db`).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from .query import MAX_FILE_MB_DEFAULT, _merge

log = logging.getLogger("chatbot")


def _gaze_str(collector, attr: str) -> str:
    """One of the collector's text run counters, as the gaze table stores it."""
    return str(getattr(collector, attr, "") or "")


def _gaze_int(collector, attr: str) -> str:
    """One of the collector's numeric run counters, as gaze stores it."""
    return str(int(getattr(collector, attr, 0) or 0))


def _gaze_rows(collector, nick: str) -> list:
    """The run counters worth remembering when the app closes.

    Module-level (not a method) because `HistoryMutateService` is at the RULE 16
    method cap, and this is a pure projection of the collector.
    """
    return [("partner", nick),
            ("added", _gaze_int(collector, "_added")),
            ("total", _gaze_int(collector, "_total")),
            ("last_sync_reason", _gaze_str(collector, "_last_sync_reason")),
            ("last_sync_added", _gaze_int(collector, "_last_sync_added")),
            ("last_sync_count", _gaze_int(collector, "_last_sync_count"))]


class SettingsMutateMixin:
    """App settings and gaze rows; mixed into ``HistoryService``."""

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

    def _app_setting_rows(self) -> list[tuple]:
        """The four app_settings rows, built once for both write paths.

        `_persist_app_settings` and `seed_app_settings` used to build this same
        list inline; it is one named concept (RULE 16 §16.4 — duplicated logic
        becomes a helper in the owning layer). `media` is read defensively
        because `seed_app_settings` always did; `HISTORY_DEFAULTS` guarantees
        the key, so both call sites behave exactly as before.
        """
        media = self._settings.get("media") or {}
        return [("my_nick", json.dumps(self.collector.my_nick or "")),
                ("media_max_file_mb", json.dumps(media.get("max_file_mb", MAX_FILE_MB_DEFAULT))),
                ("media_max_cache_mb", json.dumps(media.get("max_cache_mb", 200))),
                ("preview", json.dumps(self._settings.get("preview") or {}))]

    def _persist_app_settings(self) -> None:
        if not self.db.is_open:
            return
        stamp = datetime.now().isoformat(timespec="seconds")
        rows = self._app_setting_rows()

        async def work():
            try:
                for key, value in rows:
                    await self.db.execute("INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (key, value, stamp))
                await self.db.commit()
            except Exception as exc:
                log.debug("persist app settings failed: %s", exc)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        # The task must be referenced or CPython may collect it before it runs
        # — the event loop holds only a weak reference to pending tasks, so an
        # unreferenced one can vanish and silently drop the write. Latent
        # since this persist was added; it started biting on 2026-09-14 when
        # the larger Round H suite raised GC pressure enough to collect it.
        pending = self.__dict__.setdefault("_pending_persist_tasks", set())
        task = loop.create_task(work())
        pending.add(task)
        task.add_done_callback(pending.discard)

    async def seed_app_settings(self) -> None:
        have = {row["key"] for row in await self.db.fetchdicts("SELECT key FROM app_settings")}
        stamp = datetime.now().isoformat(timespec="seconds")
        for key, value in self._app_setting_rows():
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
