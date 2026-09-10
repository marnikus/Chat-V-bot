"""Create / load / delete / clean the archive database — ONE DB = ONE WORLD.

Since the unified single-DB redesign (docs/DB_CREATION_DELETION_REDESIGN_
DESIGN_2026-09-08.md) a database file is a complete, self-contained world
(messages, people queue, labels, undo, radar state, settings, and its own
media folder). This module owns the lifecycle rules:

* **delete is permanent.** Deleting a world removes its file, its
  `-wal`/`-shm` siblings, its media (a reference scan across the other
  worlds keeps files that two worlds share) and every reference to it.
  There is no trash copy and no restore — the UI says so before it asks.
* **the last world cannot be deleted.** The system must always have at
  least one database; deleting the only remaining one is refused here (the
  DB window mirrors the decision by disabling its button with a tooltip).
* **clean break.** After a deletion there are no "missing" ghost rows left
  in the list, no `db_recent` entry pointing at a file that is gone, no
  `history.db_path` at a deleted file, and no other world's media row
  pointing at an unlinked file.
* **a failed swap leaves the app connected.** Switching databases closes
  the live connection, and if the new file cannot be opened the previous
  one is re-opened before the error is reported (fail closed).
* **Clean DB stays reversible.** Emptying a world's tables is an edit, not
  a deletion: the file backup goes to `db_trash/` and Ctrl+Z restores it,
  exactly like every other editable surface (AGENT_RULES RULE 12).
"""

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
                f"file:{os.path.abspath(path)}?mode=ro", uri=True) as conn:
            cur = await conn.execute(
                "SELECT cache_path FROM media "
                "WHERE state='cached' AND cache_path<>'' AND cache_path IS NOT NULL")
            for (cache_path,) in await cur.fetchall():
                text = str(cache_path or "").strip()
                if text:
                    refs.add(os.path.abspath(text))
    except Exception as exc:                         # noqa: BLE001
        log.debug("no media references readable from %s: %s", path, exc)
    return refs


class DbManager:
    """Lifecycle + size reporting for the world database files.

    AREA C split: `DbRegistry` (services/db_registry.py) owns the reads —
    path resolution with the containment rule, the remembered-path list,
    the world scan, the DB-window list and info. `DbLifecycle`
    (services/db_lifecycle.py) owns the writes — create/load/delete/clean/
    restore_backup with the media-reference scans. Every public name this
    class exposed before is a one-line delegate, so callers (the frozen
    `backend/db_manager.py` shim, `bridge/db_bridge.py`,
    `services/undo_service.py`) see no change.
    """

    def __init__(self, config=None, service=None, root: str = ""):
        self._config = config
        self._service = service
        self.root = root or os.getcwd()
        # function-local to avoid the db_service ↔ db_registry module cycle
        from services.db_lifecycle import DbLifecycle
        from services.db_registry import DbRegistry
        self.registry = DbRegistry(self)
        self.lifecycle = DbLifecycle(self)

    # ── wiring ───────────────────────────────────────────────────
    def attach(self, service) -> None:
        self._service = service

    @property
    def service(self):
        return self._service

    # ── registry delegates (reads) ───────────────────────────────
    def active_path(self) -> str:
        return self.registry.active_path()

    def resolve(self, name_or_path: str) -> str:
        return self.registry.resolve(name_or_path)

    def trash_dir(self) -> str:
        return self.registry.trash_dir()

    def media_base_dir(self) -> str:
        return self.registry.media_base_dir()

    def media_dir(self, path: str = "") -> str:
        return self.registry.media_dir(path)

    def known_paths(self) -> list[str]:
        return self.registry.known_paths()

    def _remember(self, path: str) -> None:
        self.registry._remember(path)

    def _prune_remembered(self) -> None:
        self.registry._prune_remembered()

    def existing_worlds(self) -> list[str]:
        return self.registry.existing_worlds()

    def list_dbs(self) -> list[dict]:
        return self.registry.list_dbs()

    async def info(self) -> dict:
        return await self.registry.info()

    # ── lifecycle delegates (writes) ─────────────────────────────
    async def create(self, name: str) -> dict:
        return await self.lifecycle.create(name)

    async def load(self, path: str, create: bool = False) -> dict:
        return await self.lifecycle.load(path, create)

    async def delete(self, path: str) -> dict:
        return await self.lifecycle.delete(path)

    async def clean(self) -> dict:
        return await self.lifecycle.clean()

    async def restore_backup(self, backup: str, target: str = "") -> dict:
        return await self.lifecycle.restore_backup(backup, target)
