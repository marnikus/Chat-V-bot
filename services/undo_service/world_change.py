"""The world-change wire half: how a DB result is announced, and what a
create / load / delete drags along.

Two module-level functions, both imported by name from `bridge/db_bridge.py`
(and re-exported by the package `__init__`, so that import line is unchanged):

* `emit_db_change` — formats a `DbManager` result as the `db_changed` payload
  and decides WHEN a world counts as *switched* (a failed, unchanged or
  offline result is not one), which is what tells every JS window to drop the
  world data it cached.
* `restart_world` — after the service tore the old world down and rebuilt the
  database side, the rest of the app follows via bus events: the people queue
  follows the file, the undo timeline is re-synced, the windows are told to
  reload, and the my-nick readout follows.

`dbconn` undo/redo (`dbconn.py`) calls both: reversing a world action has to
announce itself exactly like the action did.

Extracted unchanged from `services/undo_service.py` (god-class round, step 7).
See `docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from __future__ import annotations

import json
import logging
import os

from core.events import (EventBus, DbChanged, LogMessage, UserDbChanged)
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


async def restart_world(memory, archive, labels, undo, bus: EventBus,
                        op: str) -> None:
    """After a world create/load/delete: rebuild every world-bound surface.

    The service already tore the old world down and rebuilt the database
    side (queue connection, labels, radar state, per-world settings);
    here the rest of the app follows via bus events: undo timeline,
    People list, Full User Database, labels and the my-nick readout.
    """
    if archive is None:
        return
    if memory is not None:
        try:
            if os.path.abspath(memory.db_path) != \
                    os.path.abspath(archive.db.path):
                await memory.switch_db(archive.db.path)
        except Exception as exc:                        # noqa: BLE001
            log.warning("queue did not follow the world switch: %s", exc)
    if undo is not None:
        try:
            await undo.sync_world_state()
        except Exception as exc:                        # noqa: BLE001
            log.warning("world undo sync failed: %s", exc)
    announce_world_live(bus, labels, reason="db_switch")
    try:
        bus.emit(LogMessage(message="👤 my nick follows the world", level="debug"))
        from core.events import MyNickChanged
        bus.emit(MyNickChanged(nick=archive.my_nick))
    except Exception:                                   # noqa: BLE001
        pass
    log.info("world %s is live — all world state rebuilt (%s)",
             os.path.basename(archive.db.path), op)
