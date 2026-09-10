"""Persist and merge the app/world halves of one timeline."""

from __future__ import annotations
import asyncio
import copy
import logging
from core.events import UndoHistoryChanged
from core.result import Ok, Result

log = logging.getLogger("chatbot")


class UndoWorldStore:
    def _next_seq(self) -> int:
        next_seq = self._seq_next
        self._seq_next = next_seq + 1
        return next_seq

    def _commit_timeline(self, history: list, index: int) -> None:
        """Persist the ONE timeline split by ownership (app vs world)."""
        for entry in history:
            if isinstance(entry, dict) and (
                not isinstance(entry.get("seq"), int) or entry["seq"] <= 0
            ):
                entry["seq"] = self._next_seq()
        self._timeline = history
        self._h_index = index
        self._seq_next = (
            max(
                [
                    e["seq"]
                    for e in history
                    if isinstance(e, dict) and isinstance(e.get("seq"), int)
                ],
                default=0,
            )
            + 1
        )
        service = self._archive
        if service is None or not getattr(service.db, "is_open", False):
            self._config.set_state(
                undo_history=copy.deepcopy(history), undo_history_index=index
            )
            return
        app_entries = [e for e in history if e.get("kind") not in self.WORLD_UNDO_KINDS]
        world_entries = [e for e in history if e.get("kind") in self.WORLD_UNDO_KINDS]
        self._config.set_state(
            undo_history=copy.deepcopy(app_entries), undo_history_index=index
        )
        self._schedule_world_undo_save(world_entries)

    def _schedule_world_undo_save(self, entries: list) -> None:
        """Persist the world half, tracking the task so a later
        `sync_world_state` can wait for it."""
        service = self._archive
        if service is None or not getattr(service.db, "is_open", False):
            return

        async def runner():
            try:
                await service.save_world_undo(entries)
            except Exception as exc:  # noqa: BLE001
                log.warning("world undo save failed: %s", exc)

        try:
            task = asyncio.ensure_future(runner())
        except RuntimeError:
            return
        self._undo_pendings.append(task)
        task.add_done_callback(self._undo_pendings.remove)

    async def sync_world_state(self) -> Result[None]:
        """Rebuild the unified timeline from both stores after a world
        change (startup or switch): config's app-level half + the active
        world's `undo_history` table, merged by `seq`."""
        pending = list(self._undo_pendings)
        if pending:
            try:
                await asyncio.gather(*pending, return_exceptions=True)
            except Exception:  # noqa: BLE001
                pass
        service = self._archive
        world_entries: list[dict] = []
        if service is not None and getattr(service.db, "is_open", False):
            try:
                world_entries = await service.load_world_undo()
            except Exception as exc:  # noqa: BLE001
                log.warning("world undo load failed: %s", exc)
        app_entries: list[dict] = []
        raw = self._config.get_state("undo_history", None)
        if isinstance(raw, list):
            for entry in raw:
                if not (isinstance(entry, dict) and isinstance(entry.get("kind"), str)):
                    continue
                if service is not None and entry.get("kind") in self.WORLD_UNDO_KINDS:
                    continue  # the world table is the truth
                app_entries.append(copy.deepcopy(entry))
        merged = app_entries + world_entries
        merged.sort(
            key=lambda e: (
                isinstance(e.get("seq"), int) and e["seq"] > 0,
                e.get("seq") if isinstance(e.get("seq"), int) else 0,
            )
        )
        self._commit_timeline(merged, len(merged) - 1)
        self._bus.emit(UndoHistoryChanged())
        return Ok(None)
