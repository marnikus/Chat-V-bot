"""Undo/redo of the DB Connection actions — the world-changing command kind.

A `dbconn` entry carries an op (`create` / `load` / `delete` / `clean`) plus
the paths involved, so reversing one means running a different op, not
restoring a snapshot:

| op | redo (forward) | undo (backward) |
|---|---|---|
| `create` / `load` | `manager.load(path, create=…)` | `manager.load(before_path)` |
| `delete` | `manager.delete(path)` | `manager.restore_backup(backup, path)` |
| `clean` | `manager.clean()` | `manager.restore_backup(backup, path)` |

Two refusals must stay LOUD and must never be reported as successes — they are
the dbconn shape of the 2026-09-11 bug:

* undoing a delete with no backup: "⚠ Database deletions are permanent — no
  backup exists to restore";
* re-deleting a file that is already gone: "⚠ Nothing to re-delete".

Both return `None`, which means "warned already — nothing to do": no
`restart_world`, no `db_changed`, because no world changed. When the op DID
succeed, `restart_world` rebuilds every world-bound surface and
`emit_db_change` announces it exactly as the original action did — including
the `switched` flag that tells the JS windows to drop their cached world.

Everything runs inside ONE spawned task (`TimelineCommit.spawn`), so the
bridge's slot answers immediately and the world work is tracked as a pending
task that a later `sync_world_state` waits for.

Extracted unchanged from `services/undo_service.py` (god-class round, step 7).
See `docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from __future__ import annotations

import os

from .world_change import emit_db_change, restart_world


class DbConnMixin:
    """Re-apply / reverse a DB Connection action, and announce the world."""

    def _apply_db_command(self, value: dict, forward: bool) -> bool:
        """Re-apply / reverse a DB Connection action (legacy entries)."""
        op = str(value.get("op") or "")

        async def work():
            if op == "delete":
                result = await self._db_delete_op(value, forward)
                if result is None:          # warned already — nothing to do
                    return
                if result.get("ok"):
                    await restart_world(self._memory, self._archive,
                                        self._labels, self, self._bus,
                                        "delete")
                emit_db_change(self._bus, "delete", result)
                return
            result = await self._db_switch_op(value, forward)
            if result is None:              # unknown op — nothing to do
                return
            if op in ("create", "load") and result.get("ok") \
                    and not result.get("unchanged"):
                await restart_world(self._memory, self._archive,
                                    self._labels, self, self._bus, op)
            emit_db_change(self._bus, op, result)
        self._timeline_commit.spawn("db command", work())
        return True

    async def _db_delete_op(self, value: dict, forward: bool):
        """Run a delete re-apply (forward) or backup restore (undo)."""
        manager = self._dbs
        if forward:
            path = str(value.get("path") or "")
            if not os.path.exists(path):
                self._log("⚠ Nothing to re-delete — the file is "
                          "already gone", "warn")
                return None
            return await manager.delete(path)
        backup = str(value.get("backup") or "")
        if not os.path.exists(backup):
            self._log("⚠ Database deletions are permanent — "
                      "no backup exists to restore", "warn")
            return None
        return await manager.restore_backup(backup,
                                            str(value.get("path") or ""))

    async def _db_switch_op(self, value: dict, forward: bool):
        """Run a create/load/clean re-apply or its reverse."""
        manager = self._dbs
        op = str(value.get("op") or "")
        backup = str(value.get("backup") or "")
        path = str(value.get("path") or "")
        if forward:
            if op in ("create", "load"):
                return await manager.load(path, create=(op == "create"))
            if op == "clean":
                return await manager.clean()
            return None
        if op in ("create", "load"):
            return await manager.load(str(value.get("before_path") or ""))
        if op == "clean":
            return await manager.restore_backup(backup, path)
        return None
