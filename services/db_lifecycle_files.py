"""World-file bookkeeping for `DbLifecycle` (Round H step H-C3).

Everything that touches a world *file* rather than a world *operation*: the
timestamped trash copies `clean` and `delete` leave behind, the restore copy
that puts one back, the config's `history.db_path` pointer, and the choice of
which database to open after the active one is permanently deleted.

Mixed into `services.db_lifecycle.DbLifecycle`, which keeps the serialized
public surface; the five unlocked operations are in `db_lifecycle_ops.py`.
Both are mixins, not collaborators, so `lifecycle._forget(...)` and
`lifecycle._copy_to_trash(...)` keep resolving exactly as before for
`services/db_deletion_flow*.py` and the safety-deletion tests.

Import direction: `services.db_service` for the file suffixes; no Qt, no CDP.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime

from services.db_service import SUFFIXES

log = logging.getLogger("chatbot")


def stamp(tag: str, name: str) -> str:
    """The timestamped name every trash copy and backup is filed under."""
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{tag}_{name}"


def copy_backup_trio(source: str, destination: str) -> dict | None:
    """Copy a backup's db+wal+shm into place; an err-dict when that failed.

    Module-level because it is a pure filesystem move between two paths —
    it reads nothing from the lifecycle object.
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(destination)) or ".",
                    exist_ok=True)
        for suffix in SUFFIXES:
            if not os.path.exists(source + suffix):
                continue
            shutil.copyfile(source + suffix, destination + suffix)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return None


class WorldFilesMixin:
    """Trash copies and the config pointer; mixed into ``DbLifecycle``."""

    def _stamp(self, tag: str, name: str) -> str:
        return stamp(tag, name)

    def _copy_to_trash(self, path: str, tag: str = "backup") -> str:
        trash = self._registry.trash_dir()
        try:
            os.makedirs(trash, exist_ok=True)
            target = os.path.join(trash,
                                  self._stamp(tag, os.path.basename(path)))
            for suffix in SUFFIXES:
                if os.path.exists(path + suffix):
                    shutil.copyfile(path + suffix, target + suffix)
            return target
        except OSError as exc:
            log.warning("cannot back up %s: %s", path, exc)
            return ""

    def _persist_path(self, path: str) -> None:
        if self._config is None:
            return
        history = self._config.get("history", default={}) or {}
        if not isinstance(history, dict):
            history = {}
        history = dict(history)
        history["db_path"] = path
        self._config.set("history", history)
        self._config.save()

    def _forget(self, path: str) -> None:
        """Clean break: no reference to the deleted file survives."""
        self._registry._prune_remembered()
        if self._config is None:
            return
        stored = self._config.get("history", "db_path", default="")
        if isinstance(stored, str) and \
                os.path.abspath(stored) == os.path.abspath(path):
            replacement = self._registry.active_path()
            if replacement and os.path.exists(replacement) and \
                    os.path.abspath(replacement) != os.path.abspath(path):
                history = self._config.get("history", default={}) or {}
                if not isinstance(history, dict):
                    history = {}
                history = dict(history)
                history["db_path"] = replacement
                self._config.set("history", history)
                self._config.save()

    def _pick_fallback(self, deleted: str) -> str:
        """Which database to open after the active one is deleted."""
        for item in self._registry.list_dbs():
            if (os.path.abspath(item["path"]) != os.path.abspath(deleted)
                    and item.get("exists")):
                return item["path"]
        return ""
