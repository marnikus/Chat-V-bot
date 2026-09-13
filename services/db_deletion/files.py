"""Bounded filesystem helpers: one unlink, one rmdir, never rmtree.

`unlink_one` removes exactly one file (idempotent on missing, refuses
symlinks and directories). `prune_empty_dirs` rmdirs verified-empty
directories strictly inside the media base. Imports `paths` only.
"""

from __future__ import annotations

import logging
import os

from .paths import is_within

from services import db_deletion

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
        base_c = db_deletion.canonical(base)
    except Exception:  # noqa: BLE001
        base_c = base
    other_c: set[str] = set()
    for other in (other_world_folders or frozenset()):
        try:
            other_c.add(db_deletion.canonical(other))
        except Exception:  # noqa: BLE001
            continue
    return base, base_c, other_c


def _prune_blocked(folder_c: str, folder: str, guard) -> bool:
    """True when verified-empty upward pruning must stop at `folder`."""
    base, base_c, other_c = guard
    if folder_c == base_c:
        return True
    if not is_within(folder, base):
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
            folder_c = db_deletion.canonical(folder)
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
