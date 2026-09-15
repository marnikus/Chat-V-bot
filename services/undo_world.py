"""The world-bound half of the undo timeline — and the two module-level
functions the rest of the app reaches for when a world changes.

Owns `emit_db_change` and `restart_world` (both moved here verbatim from
`services/undo_service.py`, which re-exports them so `bridge/db_bridge.py`,
`bridge/router.py`, `tests/unit/services/test_world_events.py` and
`tests/test_world_write_gate.py` keep importing them from there), plus
`WorldSync`: rebuilding the unified timeline from both stores after a world
switch, and scheduling the world half's save.

Imports point one way: this module imports `core` and `services.world_events`
only, never `services.undo_service`. `UndoService` owns every attribute this
reads and writes; `WorldSync` reaches them through `self._o`, so the state a
test pokes is the same object it was before the split.
"""

from __future__ import annotations

import copy
import json
import logging
import os

from core.events import (EventBus, DbChanged, LogMessage, UndoHistoryChanged,
                         UserDbChanged)
from core.result import Ok, Result
from services.wiring_requests import RestartDeps  # noqa: F401  (re-exported)
from services.world_events import announce_world_live

log = logging.getLogger("chatbot")


def emit_db_change(bus: EventBus, action: str, result) -> None:
    """Format a DbManager result as the db_changed wire payload."""
    payload = dict(result or {})
    payload["action"] = action
    if action in ("create", "load", "delete") and payload.get("ok") \
            and not payload.get("unchanged") and not payload.get("offline"):
        # a different world is live now — every JS window that caches
        # world data must drop it
        payload["switched"] = True
    bus.emit(DbChanged(action=action,
                       payload=json.dumps(payload, ensure_ascii=False)))
    bus.emit(UserDbChanged(payload=json.dumps(
        {"action": "db_" + action, "ok": bool(payload.get("ok"))},
        ensure_ascii=False)))
    if payload.get("error"):
        bus.emit(LogMessage(message="⚠ " + str(payload["error"]),
                            level="warn"))


async def restart_world(deps: RestartDeps, op: str) -> None:
    """After a world create/load/delete: rebuild every world-bound surface.

    The service already tore the old world down and rebuilt the database
    side (queue connection, labels, radar state, per-world settings);
    here the rest of the app follows via bus events: undo timeline,
    People list, Full User Database, labels and the my-nick readout.
    """
    if deps.archive is None:
        return
    if deps.memory is not None:
        try:
            if os.path.abspath(deps.memory.db_path) != \
                    os.path.abspath(deps.archive.db.path):
                await deps.memory.switch_db(deps.archive.db.path)
        except Exception as exc:                        # noqa: BLE001
            log.warning("queue did not follow the world switch: %s", exc)
    if deps.undo is not None:
        try:
            await deps.undo.sync_world_state()
        except Exception as exc:                        # noqa: BLE001
            log.warning("world undo sync failed: %s", exc)
    announce_world_live(deps.bus, deps.labels, reason="db_switch")
    try:
        deps.bus.emit(LogMessage(message="👤 my nick follows the world", level="debug"))
        from core.events import MyNickChanged
        deps.bus.emit(MyNickChanged(nick=deps.archive.my_nick))
    except Exception:                                   # noqa: BLE001
        pass
    log.info("world %s is live — all world state rebuilt (%s)",
             os.path.basename(deps.archive.db.path), op)


class WorldSync:
    """Rebuild ONE timeline out of two stores when the world changes.

    The app-level half lives in config, the world-bound half in the active
    world's ``undo_history`` table; `seq` is the identity they merge on.
    """

    def __init__(self, owner):
        self._o = owner

    def _schedule_world_undo_save(self, entries: list) -> None:
        """Persist the world half, tracking the task for a later
        `sync_world_state` can wait for it."""
        self._o._world_store.schedule_save(entries)

    async def sync_world_state(self) -> Result[None]:
        """Rebuild the unified timeline from both stores after a world
        change (startup or switch): config's app-level half + the active
        world's `undo_history` table, merged by `seq`."""
        await self._o._world_store.settle()
        world_entries: list[dict] = await self._o._world_store.load()
        service = self._o._archive
        app_entries: list[dict] = []
        raw = self._o._config.get_state("undo_history", None)
        if isinstance(raw, list):
            for entry in raw:
                if not (isinstance(entry, dict)
                        and isinstance(entry.get("kind"), str)):
                    continue
                if service is not None and \
                        entry.get("kind") in self._o.WORLD_UNDO_KINDS:
                    continue             # the world table is the truth
                app_entries.append(copy.deepcopy(entry))
        merged = app_entries + world_entries
        merged.sort(key=lambda e: (isinstance(e.get("seq"), int)
                                   and e["seq"] > 0,
                                   e.get("seq") if isinstance(e.get("seq"),
                                                              int) else 0))
        self._o._timeline_commit.commit(merged, len(merged) - 1,
                                        purge_dropped=False)
        self._o._bus.emit(UndoHistoryChanged())
        return Ok(None)
