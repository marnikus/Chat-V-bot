"""The world-scoped half of the undo timeline (H-C2 split).

One operation: undo entries whose kind belongs to a *world* — people, labels,
archive, dbconn — live in the active database's `undo_history` table and die
with the world, unlike the app-level kinds that stay in `config/undo.json`.
This module moves them there on first open (rehoming), and rewrites the whole
timeline in one transaction on every save, retrying when the world is locked.

Mixed into `HistoryService` through `mutate.HistoryMutateService`; the
app-settings writes live in `mutate_settings.py` and the legacy import in
`mutate_import.py`.

Import direction: `stores.world_lock` is the one stores edge — the save must
survive a locked world file, which is why the retry lives here and nowhere
else in the history package.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime
from functools import partial

from stores.world_lock import retry_locked

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


class WorldUndoMixin:
    """World-scoped undo entries; mixed into ``HistoryService``."""

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
