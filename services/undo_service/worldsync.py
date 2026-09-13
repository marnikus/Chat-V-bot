"""Merging the two stores back into ONE timeline after a world change.

The timeline is split by ownership: app-level entries (stack/grid) persist in
`config/undo.json`, world-bound entries (people/labels/archive/dbconn) persist
in the active world's ``undo_history`` table and die with the world. So on
startup and on every world switch the two halves have to be read back and
merged — by `seq`, the identity `TimelineMixin._next_seq` issues — into the one
chronological timeline `Ctrl+Z` walks.

The rule that keeps a stale world from surviving a switch: when an archive is
attached, the config half's copy of a WORLD kind is dropped, because the world
table is the truth for it (an app-level snapshot of a person list from the
previous world must not reappear over the new one).

Extracted unchanged from `services/undo_service.py` (god-class round, step 7).
See `docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from __future__ import annotations

import copy

from core.events import UndoHistoryChanged
from core.result import Ok, Result


class WorldSyncMixin:
    """`sync_world_state` — the config half + the world table, merged by seq."""

    async def sync_world_state(self) -> Result[None]:
        """Rebuild the unified timeline from both stores after a world
        change (startup or switch): config's app-level half + the active
        world's `undo_history` table, merged by `seq`."""
        await self._world_store.settle()
        world_entries: list[dict] = await self._world_store.load()
        service = self._archive
        app_entries: list[dict] = []
        raw = self._config.get_state("undo_history", None)
        if isinstance(raw, list):
            for entry in raw:
                if not (isinstance(entry, dict)
                        and isinstance(entry.get("kind"), str)):
                    continue
                if service is not None and \
                        entry.get("kind") in self.WORLD_UNDO_KINDS:
                    continue             # the world table is the truth
                app_entries.append(copy.deepcopy(entry))
        merged = app_entries + world_entries
        merged.sort(key=lambda e: (isinstance(e.get("seq"), int)
                                   and e["seq"] > 0,
                                   e.get("seq") if isinstance(e.get("seq"),
                                                              int) else 0))
        self._timeline_commit.commit(merged, len(merged) - 1,
                                      purge_dropped=False)
        self._bus.emit(UndoHistoryChanged())
        return Ok(None)
