"""World sync delegators — part of UndoService facade, H-C2."""

from __future__ import annotations

from core.result import Result


class UndoWorldDelegates:
    def _schedule_world_undo_save(self, entries: list) -> None:
        return self._world._schedule_world_undo_save(entries)

    async def sync_world_state(self) -> Result[None]:
        return await self._world.sync_world_state()
