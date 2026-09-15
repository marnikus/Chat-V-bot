"""Settings and gaze persistence — extracted from HistoryMutateService (H-C4/H-C5).

One named responsibility: app settings and gaze rows.
Keeps mutate orchestration, moves settings/gaze here.

Design: AREA_C H-C4 — helper named by responsibility, ≤200 LOC.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from .query import MAX_FILE_MB_DEFAULT, _merge

log = logging.getLogger("chatbot")


def _gaze_str(collector, attr: str) -> str:
    return str(getattr(collector, attr, "") or "")


def _gaze_int(collector, attr: str) -> str:
    return str(int(getattr(collector, attr, 0) or 0))


def _gaze_rows(collector, nick: str) -> list:
    return [
        ("partner", nick),
        ("added", _gaze_int(collector, "_added")),
        ("total", _gaze_int(collector, "_total")),
        ("last_sync_reason", _gaze_str(collector, "_last_sync_reason")),
        ("last_sync_added", _gaze_int(collector, "_last_sync_added")),
        ("last_sync_count", _gaze_int(collector, "_last_sync_count")),
    ]


class SettingsPersist:
    def __init__(self, owner):
        self._owner = owner

    def apply_settings(self, patch: dict) -> dict:
        patch = dict(patch or {})
        collector = patch.pop("collector", None)
        self._owner._settings = _merge(self._owner._settings, patch)
        media = self._owner._settings["media"]
        self._owner.media.enabled = bool(media.get("enabled", True))
        self._owner._apply_world_media_dir()
        self._owner.media.max_file_bytes = int(
            float(media.get("max_file_mb", MAX_FILE_MB_DEFAULT)) * 1024 * 1024
        )
        self._owner.media.max_cache_bytes = int(float(media.get("max_cache_mb", 200)) * 1024 * 1024)
        if collector:
            self._owner.collector.configure(**collector)
        if self._owner.config is not None:
            self._owner.config.set(
                "history", {k: v for k, v in self._owner._settings.items() if k != "collector"}
            )
            self._owner.config.save()
        self._persist_app_settings()
        return self._owner.settings()

    def set_my_nick(self, nick: str) -> str:
        nick = " ".join(str(nick or "").split()).strip()
        self._owner.collector.configure(my_nick=nick)
        self._persist_app_settings()
        return nick

    def _persist_app_settings(self) -> None:
        if not self._owner.db.is_open:
            return
        stamp = datetime.now().isoformat(timespec="seconds")
        media = self._owner._settings["media"]
        rows = [
            ("my_nick", json.dumps(self._owner.collector.my_nick or "")),
            ("media_max_file_mb", json.dumps(media.get("max_file_mb", MAX_FILE_MB_DEFAULT))),
            ("media_max_cache_mb", json.dumps(media.get("max_cache_mb", 200))),
            ("preview", json.dumps(self._owner._settings.get("preview") or {})),
        ]

        async def work():
            try:
                for key, value in rows:
                    await self._owner.db.execute(
                        "INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                        (key, value, stamp),
                    )
                await self._owner.db.commit()
            except Exception as exc:  # noqa: BLE001
                log.debug("persist app settings failed: %s", exc)

        try:
            asyncio.get_running_loop().create_task(work())
        except RuntimeError:
            return

    async def seed_app_settings(self) -> None:
        have = {row["key"] for row in await self._owner.db.fetchdicts("SELECT key FROM app_settings")}
        stamp = datetime.now().isoformat(timespec="seconds")
        media = self._owner._settings.get("media") or {}
        rows = [
            ("my_nick", json.dumps(self._owner.collector.my_nick or "")),
            ("media_max_file_mb", json.dumps(media.get("max_file_mb", MAX_FILE_MB_DEFAULT))),
            ("media_max_cache_mb", json.dumps(media.get("max_cache_mb", 200))),
            ("preview", json.dumps(self._owner._settings.get("preview") or {})),
        ]
        for key, value in rows:
            if key not in have:
                await self._owner.db.execute(
                    "INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?)", (key, value, stamp)
                )
        await self._owner.db.commit()

    async def save_gaze(self) -> None:
        if not self._owner.db.is_open:
            return
        nick = _gaze_str(self._owner.collector, "_nick")
        if not nick:
            return
        stamp = datetime.now().isoformat(timespec="seconds")
        try:
            for key, value in _gaze_rows(self._owner.collector, nick):
                await self._owner.db.execute(
                    "INSERT INTO gaze_data(key, value, updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, value, stamp),
                )
            await self._owner.db.commit()
        except Exception as exc:  # noqa: BLE001
            log.debug("gaze save failed: %s", exc)
