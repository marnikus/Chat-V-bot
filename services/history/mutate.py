"""History mutate — settings, gaze, legacy, world undo.

H-C4/H-C5: split by operation (settings/gaze vs legacy import vs world/undo)
into named helpers (settings.py, legacy.py). MI lifted via predicates.

Design: AREA_C H-C2, H-C4, H-C5.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime
from functools import partial

from stores.world_lock import retry_locked

from .legacy import LegacyImport
from .settings import SettingsPersist

log = logging.getLogger("chatbot")

_WORLD_KINDS = {"people", "labels", "archive", "dbconn"}


def _world_entries(raw) -> list[dict] | None:
    if not isinstance(raw, list) or not raw:
        return None
    entries = [item for item in raw if isinstance(item, dict) and isinstance(item.get("kind"), str)]
    if not any(item.get("kind") in _WORLD_KINDS for item in entries):
        return None
    return entries


def _is_world_kind(kind: str) -> bool:
    return kind in _WORLD_KINDS


def _has_seq(entry: dict) -> bool:
    return isinstance(entry.get("seq"), int)


def _is_valid_undo_entry(entry: dict) -> bool:
    return isinstance(entry, dict) and _has_seq(entry)


class HistoryMutateService:
    """Mutations: settings, gaze, legacy, world undo — mixin for HistoryService."""

    @property
    def _settings_helper(self):
        return SettingsPersist(self)

    @property
    def _legacy_helper(self):
        return LegacyImport(self)

    # ── settings / gaze ──────────────────────────────────────────
    def apply_settings(self, patch: dict) -> dict:
        return self._settings_helper.apply_settings(patch)

    def set_my_nick(self, nick: str) -> str:
        return self._settings_helper.set_my_nick(nick)

    def bind_labels(self, store) -> None:
        self._labels = store

    def _persist_app_settings(self) -> None:
        return self._settings_helper._persist_app_settings()

    async def seed_app_settings(self) -> None:
        return await self._settings_helper.seed_app_settings()

    async def save_gaze(self) -> None:
        return await self._settings_helper.save_gaze()

    # ── legacy ───────────────────────────────────────────────────
    async def _legacy_user_rows(self, legacy_path: str) -> list[dict]:
        return await self._legacy_helper._legacy_user_rows(legacy_path)

    async def _insert_legacy_users(self, legacy: list[dict]) -> int:
        return await self._legacy_helper._insert_legacy_users(legacy)

    async def _merge_legacy_queue(self, legacy_path: str) -> None:
        return await self._legacy_helper._merge_legacy_queue(legacy_path)

    async def _import_config_labels(self) -> bool:
        return await self._legacy_helper._import_config_labels()

    # ── world undo ───────────────────────────────────────────────
    async def set_meta_flag(self, key: str) -> None:
        try:
            await self.db.set_meta(key, "1")
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("cannot set migration flag %s: %s", key, exc)

    def _backfill_seqs(self, entries: list[dict]) -> None:
        if all(not _has_seq(item) for item in entries):
            for seq, entry in enumerate(entries, start=1):
                entry["seq"] = seq
            self.config.set_state(undo_history=copy.deepcopy(entries))

    async def _insert_world_entries(self, entries, stamp) -> int:
        moved = 0
        for entry in entries:
            if not _is_world_kind(entry.get("kind")):
                continue
            await self.db.execute(
                "INSERT OR IGNORE INTO undo_history(seq, kind, value, created_at) VALUES(?,?,?,?)",
                (int(entry.get("seq") or 0), entry["kind"], json.dumps(entry.get("value"), ensure_ascii=False), stamp),
            )
            moved += 1
        await self.db.commit()
        return moved

    async def _rehome_undo_entries(self) -> bool:
        entries = _world_entries(self.config.get_state("undo_history", None))
        if entries is None:
            return False
        self._backfill_seqs(entries)
        moved = await self._insert_world_entries(entries, datetime.now().isoformat(timespec="seconds"))
        if moved:
            self.config.set_state(undo_history=[e for e in entries if not _is_world_kind(e.get("kind"))])
        return bool(moved)

    async def save_world_undo(self, entries: list[dict]) -> None:
        if not self.db.is_open:
            return
        try:
            await retry_locked(partial(_write_world_undo, self, _undo_rows(entries)))
        except Exception as exc:  # noqa: BLE001
            log.warning("undo save to %s failed: %s", self.db.path, exc)


def _undo_rows(entries: list) -> list[tuple]:
    stamp = datetime.now().isoformat(timespec="seconds")
    return [
        (int(e["seq"]), str(e.get("kind") or ""), json.dumps(e.get("value"), ensure_ascii=False), stamp)
        for e in entries or []
        if _is_valid_undo_entry(e)
    ]


async def _write_world_undo(host, rows: list[tuple]) -> None:
    await host.db.execute("DELETE FROM undo_history")
    await host.db.executemany("INSERT OR IGNORE INTO undo_history(seq, kind, value, created_at) VALUES(?,?,?,?)", rows)
    await host.db.execute("DELETE FROM sqlite_sequence WHERE name='undo_history'")
    await host.db.commit()
