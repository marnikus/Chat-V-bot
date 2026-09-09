"""Path identity and boundaries shared by archive lifecycle entry points."""

from __future__ import annotations

import os
from pathlib import Path

PROTECTED_DATABASE = "This database is reserved for People or undo history and cannot be managed here."
RESERVED_NAMES = {"chatbot.db", "undo.db", "undo_history.db", "undo-history.db", "undohistory.db"}


def canonical_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(str(path))))


def same_database(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if canonical_path(left) == canonical_path(right):
        return True
    try:
        return os.path.samefile(left, right)  # hardlinks, not just symlinks
    except OSError:
        return False


def protected_database(path: str, *, root: str = "", memory=None) -> bool:
    """Reserved names, the actual queue path, and any aliases of those files."""
    if not path:
        return False
    target = canonical_path(path)
    if os.path.basename(target).lower() in RESERVED_NAMES or \
            os.path.basename(str(path)).lower() in RESERVED_NAMES:
        return True
    roots = {os.path.abspath(root or os.getcwd()), os.path.dirname(target), os.getcwd()}
    reserved = [os.path.join(folder, name) for folder in roots for name in RESERVED_NAMES]
    memory_path = getattr(memory, "_db_path", "")
    if memory_path:
        reserved.append(memory_path)
    return any(same_database(path, candidate) for candidate in reserved)


def in_trash(path: str) -> bool:
    return "db_trash" in {part.lower() for part in Path(canonical_path(path)).parts}
