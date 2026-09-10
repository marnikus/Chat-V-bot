"""Filesystem naming, sizing, and read-only media reference helpers."""

from __future__ import annotations

import logging
import os
import re

log = logging.getLogger("chatbot")

TRASH_DIR = "db_trash"
SUFFIXES = ("", "-wal", "-shm")
_SAFE = re.compile(r"[^0-9A-Za-z._-]+")


def safe_db_name(name: str) -> str:
    """A file name the user cannot use to escape the app folder."""
    clean = _SAFE.sub("_", str(name or "").strip()).strip("._-")
    if not clean:
        clean = "history"
    if not clean.lower().endswith(".db"):
        clean += ".db"
    return clean[:80]


def db_stem(path: str) -> str:
    """`work.db` → `work` (the name of the world's media folder)."""
    stem = os.path.splitext(os.path.basename(str(path or "")))[0]
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", stem).strip("._-")
    return stem or "world"


def folder_size(path: str) -> tuple[int, int]:
    """(bytes, files) of a directory tree; (0, 0) when it does not exist."""
    total = files = 0
    if not path or not os.path.isdir(path):
        return 0, 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(root, name))
                files += 1
            except OSError:
                continue
    return total, files


def file_group_size(path: str) -> int:
    """Size of a SQLite file including its WAL siblings."""
    total = 0
    for suffix in SUFFIXES:
        try:
            total += os.path.getsize(path + suffix)
        except OSError:
            continue
    return total


async def _media_references(path: str) -> set[str]:
    """Absolute `cache_path` values a world's `media` table points at.

    Read-only, best effort: a world file that cannot be opened (foreign
    format, locked, corrupt) simply contributes no references — and the
    caller then keeps the file rather than unlinking something it could
    not verify (never destroy what you cannot read).
    """
    refs: set[str] = set()
    import aiosqlite

    try:
        async with aiosqlite.connect(
            f"file:{os.path.abspath(path)}?mode=ro", uri=True
        ) as conn:
            cur = await conn.execute(
                "SELECT cache_path FROM media "
                "WHERE state='cached' AND cache_path<>'' AND cache_path IS NOT NULL"
            )
            for (cache_path,) in await cur.fetchall():
                text = str(cache_path or "").strip()
                if text:
                    refs.add(os.path.abspath(text))
    except Exception as exc:  # noqa: BLE001
        log.debug("no media references readable from %s: %s", path, exc)
    return refs
