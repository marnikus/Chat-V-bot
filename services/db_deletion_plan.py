"""The set of files a deletion would touch (AREA A).

Owns: `DeletionPlan` and the walk that discovers candidate files inside the
victim folder, pruning symlink directories instead of following them. Imports
down to `db_deletion_paths` and `db_deletion_inventory`; imported by
`db_deletion_policy` and the shim. Enumerates only — no safety judgement and no
deletion happens here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from services.db_deletion_inventory import DeletionInventory
from services import db_deletion_paths as _paths


@dataclass
class DeletionPlan:
    victim_abs: str
    victim_folder_abs: str
    media_base_abs: str
    footprint_files: frozenset
    discovered_files: frozenset
    keep: frozenset
    candidates: frozenset  # to remove (after policy)
    retained: frozenset    # safety exclusions (after policy)
    folder_exclusive: bool
    inventory: DeletionInventory
    other_world_folders: frozenset = frozenset()


def _prune_symlink_dirs(root: str, dirnames: list) -> None:
    """Remove symlinked subdirectories in-place so os.walk never descends.

    A stat failure is treated as 'do not descend' (same fail-closed
    posture as the link check itself).
    """
    for dirname in list(dirnames):
        full = os.path.join(root, dirname)
        try:
            if os.path.islink(full):
                dirnames.remove(dirname)
        except OSError:
            dirnames.remove(dirname)
            continue


def _add_regular_files(root: str, filenames, out: set) -> None:
    """Add regular (non-symlink) files under `root` to `out`."""
    for name in filenames:
        full = os.path.join(root, name)
        try:
            # Never include symlinks (retained by policy), and only
            # regular files (skip dirs/fifos/sockets).
            if os.path.islink(full):
                continue
            if not os.path.isfile(full):
                continue
            out.add(os.path.abspath(full))
        except OSError:
            continue


def collect_discovered_files(victim_folder_abs: str,
                             base_abs: str) -> set[str]:
    """Walk the victim folder for eligible files (no symlink dirs).

    Returns abspaths of regular files only. Symlinks are never followed and
    never returned (they are retained by policy). Raises OSError on walk
    failure so the caller treats the plan as incomplete.
    """
    out: set[str] = set()
    folder = os.path.abspath(str(victim_folder_abs or ""))
    if not folder or not os.path.isdir(folder):
        return out
    # Never walk outside base or the base itself as victim folder.
    if not _paths.is_within(folder, os.path.abspath(str(base_abs or ""))):
        return out
    for root, dirnames, filenames in os.walk(folder, topdown=True,
                                             followlinks=False):
        _prune_symlink_dirs(root, dirnames)
        _add_regular_files(root, filenames, out)
    return out
