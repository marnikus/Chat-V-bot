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
import os
from .db.paths import (
    TRASH_DIR,
    SUFFIXES,
    safe_db_name,
    db_stem,
    folder_size,
    file_group_size,
    _media_references,
)
from .db.registry import DbRegistry
from .db.lifecycle import DbLifecycle


class DbManager(DbRegistry, DbLifecycle):
    """Stable public facade over the world registry and lifecycle."""

    def __init__(self, config=None, service=None, root: str = ""):
        self._config = config
        self._service = service
        self.root = root or os.getcwd()

    def attach(self, service) -> None:
        self._service = service

    @property
    def service(self):
        return self._service
