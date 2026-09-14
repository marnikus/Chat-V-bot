"""Legacy queue and label import — extracted from HistoryMutateService (H-C4).

One named responsibility: legacy users queue and config label import.
Keeps mutate orchestration, moves legacy here.

Design: AREA_C H-C4 — helper named by responsibility, ≤200 LOC.
"""

from __future__ import annotations

import copy
import logging
import os
from datetime import datetime

log = logging.getLogger("chatbot")


def _legacy_text(row: dict, key: str, default: str = "") -> str:
    return str(row.get(key) or default)


def _legacy_flag(row: dict, key: str) -> int:
    return int(row.get(key) or 0)


def _legacy_user_params(row: dict) -> tuple:
    return (
        _legacy_text(row, "nick"),
        _legacy_text(row, "gender", "unknown"),
        _legacy_flag(row, "registered"),
        _legacy_flag(row, "anonymous"),
        _legacy_flag(row, "guest"),
        _legacy_text(row, "first_seen"),
        _legacy_text(row, "last_seen"),
        _legacy_flag(row, "messaged"),
        _legacy_flag(row, "message_count"),
        row.get("last_messaged"),
        _legacy_text(row, "notes"),
    )


def _archive_legacy_trio(legacy_path: str) -> None:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        src = legacy_path + suffix
        if os.path.exists(src):
            os.replace(src, legacy_path + f".migrated-{stamp}" + suffix)


def _config_label_state(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    defs = [item for item in (raw.get("defs") or []) if isinstance(item, dict)]
    assign = raw.get("assign") if isinstance(raw.get("assign"), dict) else {}
    if not defs and not assign:
        return None
    return {
        "defs": defs,
        "assign": assign,
        "filter": raw.get("filter") or {"include": [], "exclude": []},
        "next_id": int(raw.get("next_id") or 0),
    }


class LegacyImport:
    def __init__(self, owner):
        self._owner = owner

    async def _legacy_user_rows(self, legacy_path: str) -> list[dict]:
        import aiosqlite

        async with aiosqlite.connect(legacy_path) as src:
            src.row_factory = aiosqlite.Row
            try:
                rows = await src.execute(
                    "SELECT nick, gender, registered, anonymous, guest, first_seen, last_seen, messaged, message_count, last_messaged, notes FROM users"
                )
                return [dict(row) for row in await rows.fetchall()]
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"cannot read {legacy_path}: {exc}")

    async def _insert_legacy_users(self, legacy: list[dict]) -> int:
        inserted = 0
        for row in legacy:
            cur = await self._owner.db.execute(
                "INSERT OR IGNORE INTO users(nick, gender, registered, anonymous, guest, first_seen, last_seen, messaged, message_count, last_messaged, notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                _legacy_user_params(row),
            )
            inserted += int(cur.rowcount or 0)
        await self._owner.db.commit()
        return inserted

    async def _merge_legacy_queue(self, legacy_path: str) -> None:
        legacy = await self._legacy_user_rows(legacy_path)
        inserted = await self._insert_legacy_users(legacy)
        _archive_legacy_trio(legacy_path)
        if self._owner.memory is not None:
            await self._owner.memory.switch_db(self._owner.db.path)
        log.info(
            "merged %d/%d queue row(s) from %s into %s",
            inserted,
            len(legacy),
            os.path.basename(legacy_path),
            os.path.basename(self._owner.db.path),
        )

    async def _import_config_labels(self) -> bool:
        state = _config_label_state(self._owner.config.get("labels", default=None))
        if state is None:
            return False
        if int(await self._owner.db.scalar("SELECT COUNT(*) FROM labels")):
            return False
        self._owner._labels._memory = copy.deepcopy(state)
        self._owner._labels._dirty = True
        await self._owner._labels.flush_to_db()
        return True
