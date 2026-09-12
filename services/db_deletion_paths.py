"""Canonical paths and containment for the deletion family (AREA A).

Owns: realpath/abspath canonicalisation plus the two containment predicates
every other `db_deletion_*` module builds on. This is the leaf of the family —
it imports nothing from it, and all four siblings may import it. Pure path
arithmetic: no Qt, no database, no filesystem mutation.
"""

from __future__ import annotations

import os


def canonical(path: str) -> str:
    """Canonical identity for comparison (symlink-aware)."""
    try:
        # realpath resolves symlinks/junctions; falls back to abspath.
        return os.path.realpath(os.path.abspath(str(path or "")))
    except Exception:  # noqa: BLE001
        try:
            return os.path.abspath(str(path or ""))
        except Exception:  # noqa: BLE001
            return str(path or "")


def is_within(child_abs: str, root_abs: str) -> bool:
    """True when `child` is strictly inside `root` (symlink-aware)."""
    try:
        child_c = canonical(child_abs)
        root_c = canonical(root_abs)
        if child_c == root_c:
            return False
        common = os.path.commonpath([root_c, child_c])
        return common == root_c
    except ValueError:  # different drives / mixed absolute
        return False
    except Exception:  # noqa: BLE001
        return False


def is_same_file(a: str, b: str) -> bool:
    try:
        return canonical(a) == canonical(b)
    except Exception:  # noqa: BLE001
        return os.path.abspath(str(a)) == os.path.abspath(str(b))
