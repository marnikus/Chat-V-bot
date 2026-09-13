"""Reversing the DB-connection entries of the undo timeline.

A `dbconn` entry records one world action — create, load, clean or delete —
with enough of its context (`path`, `before_path`, `backup`) to run it again
forward or backwards. `DbCommands` owns exactly that: turning an entry back
into a DbManager call, restarting the world when the live world really moved,
and announcing the result on the bus.

The delete half is permanent-by-design and says so: with no backup there is
nothing to restore, and the entry reports that instead of pretending.

Imports point one way: this module imports `services.undo_world` (for
`restart_world` / `emit_db_change`) and never `services.undo_service`. The
DbManager, the bus and the log line all live on the owner and are reached
through `self._o`.
"""

from __future__ import annotations

import os

from services.undo_world import emit_db_change, restart_world
from services.wiring_requests import RestartDeps


def _deps_of(o) -> RestartDeps:
    """The world's collaborators as one value — both restart calls below."""
    return RestartDeps(memory=o._memory, archive=o._archive, labels=o._labels,
                       undo=o, bus=o._bus)


def _announce(host, forward: bool, result) -> None:
    """Say "database restored" — and only once the database really was.

    The dbconn half of the 2026-09-11 fix. `undo_apply._log_command` used to
    write this line the moment `_apply_db_command` *spawned* its task, so an
    entry with nothing left to restore — a delete with no backup, which
    `_db_delete_op` can only warn about — had already announced one. `archive`
    learned this first and reports itself from the rows it read back; dbconn
    now does the same, from the DbManager's own result.

    A failed op is deliberately silent here: `emit_db_change` already turns
    `result["error"]` into a warning, and every `{"ok": False}` the DbManager
    returns carries one (12 of 12 in `services/db_lifecycle.py`), so a second
    line would only repeat it.
    """
    if not result.get("ok"):
        return
    host._log(f"{'↪ Redo' if forward else '↩ Undo'} — "
              + host.UNDO_LABELS.get("dbconn", "database restored"), "info")


class DbCommands:
    """Apply / reverse one DB-connection undo entry."""

    def __init__(self, owner):
        self._o = owner

    async def _db_delete_op(self, value: dict, forward: bool) -> dict | None:
        """The delete op (re-do / un-do).

        None means the op did not run and already said why, so the caller
        must neither restart the world nor emit a change.
        """
        path = str(value.get("path") or "")
        backup = str(value.get("backup") or "")
        if forward:
            if not os.path.exists(path):
                self._o._log("⚠ Nothing to re-delete — the file is "
                             "already gone", "warn")
                return None
            return await self._o._dbs.delete(path)
        if os.path.exists(backup):
            return await self._o._dbs.restore_backup(backup, path)
        self._o._log("⚠ Database deletions are permanent — "
                     "no backup exists to restore", "warn")
        return None

    async def _db_op_forward(self, op: str, path: str) -> dict | None:
        """The re-do half of create/load/clean; None for an unknown op."""
        if op in ("create", "load"):
            return await self._o._dbs.load(path, create=(op == "create"))
        if op == "clean":
            return await self._o._dbs.clean()
        return None

    async def _db_switch_op(self, value: dict, forward: bool) -> dict | None:
        """The create/load/clean ops (re-do / un-do); None for an unknown op.

        Un-doing a create/load goes back to ``before_path``; un-doing a clean
        restores the backup the clean made.
        """
        op = str(value.get("op") or "")
        path = str(value.get("path") or "")
        before_path = str(value.get("before_path") or "")
        backup = str(value.get("backup") or "")
        if forward:
            return await self._o._db_op_forward(op, path)
        if op in ("create", "load"):
            return await self._o._dbs.load(before_path)
        if op == "clean":
            return await self._o._dbs.restore_backup(backup, path)
        return None

    def _apply_db_command(self, value: dict, forward: bool) -> bool:
        """Re-apply / reverse a DB Connection action (legacy entries)."""
        op = str(value.get("op") or "")

        async def work():
            if op == "delete":
                result = await self._o._db_delete_op(value, forward)
                if result is None:   # the op already said why it did not run
                    return
                if result.get("ok"):
                    await restart_world(_deps_of(self._o), "delete")
                _announce(self._o, forward, result)
                emit_db_change(self._o._bus, "delete", result)
                return
            result = await self._o._db_switch_op(value, forward)
            if result is None:       # unknown op — nothing to apply or emit
                return
            if op in ("create", "load") and result.get("ok") \
                    and not result.get("unchanged"):
                await restart_world(_deps_of(self._o), op)
            _announce(self._o, forward, result)
            emit_db_change(self._o._bus, op, result)
        self._o._timeline_commit.spawn("db command", work())
        return True
