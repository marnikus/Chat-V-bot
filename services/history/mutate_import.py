"""One-time import of legacy state into the current world (H-C2 split).

One operation: bring in what an older installation left behind — the `users`
queue of a pre-world database file, and a label store the global config file
still carries — then archive what was consumed so the import cannot run twice.

Mixed into `HistoryService` through `mutate.HistoryMutateService`; the
app-settings writes live in `mutate_settings.py` and the world undo entries in
`mutate_world.py`.

Import direction: stdlib plus the host's `self.db`; `aiosqlite` is imported
inside the one method that opens the *legacy* file, so this module does not
depend on it at import time.
"""

from __future__ import annotations

import copy
import logging
import os
from datetime import datetime

log = logging.getLogger("chatbot")


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


class LegacyImportMixin:
    """Legacy queue and label import; mixed into ``HistoryService``."""

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
