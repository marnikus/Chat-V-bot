"""Bounded filesystem execution and its outcome (AREA A).

Owns: the single-file unlink, empty-directory pruning and the `DeletionOutcome`
report. Imports down to `db_deletion_paths`; imported only by the shim. Every
operation here is bounded — one unlink or one rmdir at a time, never rmtree, and
symlinks are never followed.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from services import db_deletion_paths as _paths

log = logging.getLogger("chatbot")


def unlink_one(path: str) -> tuple[bool, str]:
    """Unlink one file; missing is success (idempotent). Never follows dirs.

    Returns (ok, error). Symlinks are never unlinked here (retained by
    policy); callers must have classified first. As a belt-and-braces guard,
    refuse to unlink a symlink or a directory.
    """
    try:
        # Never unlink symlinks or dirs via this helper.
        try:
            if os.path.islink(path):
                return False, "refused: symlink"
            if os.path.isdir(path) and not os.path.isfile(path):
                return False, "refused: not a file"
        except OSError as exc:
            return False, str(exc)
        if not os.path.lexists(path):
            return True, ""
        os.unlink(path)
        return True, ""
    except FileNotFoundError:
        return True, ""
    except OSError as exc:
        return False, str(exc)


def _prune_roots(base_abs: str, other_world_folders):
    """Canonical guard roots: (base abspath, canonical base, canonical others)."""
    base = os.path.abspath(str(base_abs or ""))
    try:
        base_c = _paths.canonical(base)
    except Exception:  # noqa: BLE001
        base_c = base
    other_c: set[str] = set()
    for other in (other_world_folders or frozenset()):
        try:
            other_c.add(_paths.canonical(other))
        except Exception:  # noqa: BLE001
            continue
    return base, base_c, other_c


def _prune_blocked(folder_c: str, folder: str, guard) -> bool:
    """True when verified-empty upward pruning must stop at `folder`."""
    base, base_c, other_c = guard
    if folder_c == base_c:
        return True
    if not _paths.is_within(folder, base):
        return True
    if folder_c in other_c:
        # Never prune another world's folder.
        return True
    try:
        if not os.path.isdir(folder) or os.path.islink(folder):
            return True
        if os.listdir(folder):
            return True
    except OSError:
        return True
    return False


def _prune_one_start(start, guard, seen: set, removed: list) -> None:
    """Walk upward from one parent dir while it stays removable."""
    folder = os.path.abspath(str(start or ""))
    while folder and folder not in seen:
        seen.add(folder)
        try:
            folder_c = _paths.canonical(folder)
        except Exception:  # noqa: BLE001
            break
        if _prune_blocked(folder_c, folder, guard):
            break
        try:
            os.rmdir(folder)
            removed.append(folder)
        except OSError as exc:
            log.debug("cannot prune %s: %s", folder, exc)
            break
        folder = os.path.dirname(folder)


def prune_empty_dirs(*, start_dirs, base_abs: str,
                     other_world_folders: frozenset) -> list[str]:
    """Rmdir verified-empty dirs strictly inside base (never base/others).

    `start_dirs` are parent dirs of removed files. Walks upward while empty.
    Never rmtree. Returns removed dir paths.
    """
    guard = _prune_roots(base_abs, other_world_folders)
    seen: set[str] = set()
    removed: list[str] = []
    for start in (start_dirs or []):
        _prune_one_start(start, guard, seen, removed)
    return removed



def _as_list(value) -> list:
    """List copy of an outcome field (None-safe; outcomes default to lists)."""
    return list(value or [])


@dataclass
class DeletionOutcome:
    ok: bool
    phase: str  # validate | scan | switch | detach | database | media | finalize
    error: str = ""
    partial: bool = False
    world_changed: bool = False
    active_path: str = ""
    removed_paths: list = field(default_factory=list)
    retained_paths: list = field(default_factory=list)
    failed_paths: list = field(default_factory=list)
    media_files_removed: int = 0
    # compat
    op: str = "delete"
    path: str = ""
    was_active: bool = False
    before_path: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {
            "ok": bool(self.ok),
            "op": self.op or "delete",
            "path": self.path,
            "was_active": bool(self.was_active),
            "before_path": self.before_path or self.path,
            "media_files_removed": int(self.media_files_removed or 0),
            "phase": self.phase,
            "partial": bool(self.partial),
            "world_changed": bool(self.world_changed),
            "active_path": self.active_path,
            "removed_paths": _as_list(self.removed_paths),
            "retained_paths": _as_list(self.retained_paths),
            "failed_paths": _as_list(self.failed_paths),
        }
        if self.error:
            d["error"] = self.error
        # Preserve last_database flag and diagnostics when present.
        if self.extra:
            for k, v in self.extra.items():
                if k not in d:
                    d[k] = v
        return d
