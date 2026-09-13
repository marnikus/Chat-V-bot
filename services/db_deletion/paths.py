"""Canonical paths, containment, and defensive path helpers.

The leaf of the deletion family's dependency order: no imports from the rest
of the package. `canonical` is the one name the safety tests patch
(`services.db_deletion.paths.canonical`), so `is_within` / `is_same_file`
must call it through this module's own global to stay symlink-aware.
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


def lexists(path: str) -> bool:
    """os.path.lexists that treats a stat OSError as 'absent'."""
    try:
        return os.path.lexists(path)
    except OSError:
        return False


def abspath_or_none(value):
    """Abspath of ``value`` (stringified), or None on any failure."""
    try:
        return os.path.abspath(str(value))
    except Exception:  # noqa: BLE001
        return None


def same_canonical(a: str, b: str) -> bool:
    """Symlink-aware equality that never raises."""
    try:
        return canonical(a) == canonical(b)
    except Exception:  # noqa: BLE001
        return False
