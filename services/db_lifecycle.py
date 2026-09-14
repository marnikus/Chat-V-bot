"""DbLifecycle — the write half of `services.db_service.DbManager` (AREA C).

Owns every MUTATION of the world databases: create, load, delete, clean
and restore_backup. Round H step H-C3 split the three responsibilities this
file had accumulated into one module each, leaving here the one thing that
must stay in one place — the serialization every mutation goes through:

    db_lifecycle.py        DbLifecycle      locks + the five public ops
    db_lifecycle_ops.py    WorldOpsMixin    what each op does, unlocked
    db_lifecycle_files.py  WorldFilesMixin  trash copies, the config pointer

The two mixins are inherited, not delegated to, so `lifecycle._forget(...)`,
`lifecycle._load_unlocked(...)` and friends keep resolving for
`services/db_deletion_flow*.py` and the safety-deletion tests.

The registry reads (paths, remembered list, scans, info) live in
`services.db_registry.DbRegistry`; this collaborator calls them through its
host.

Every rule from the ONE DB = ONE WORLD design is preserved verbatim
(permanent delete, last-world protection, fail-closed switching, clean
with a trash backup).

AREA A (2026-09-10): deletion is fail-closed and serialized. Scans happen
before any switch/unlink; any incomplete scan refuses; per-file keep is never
bypassed by rmtree; partial work is reported truthfully; overlapping lifecycle
ops serialize via per-manager + root-global locks with unlocked delegates.
"""

from __future__ import annotations

import asyncio
import logging
import os

from .db_lifecycle_files import WorldFilesMixin
from .db_lifecycle_ops import WorldOpsMixin

log = logging.getLogger("chatbot")

# Root-keyed global locks for cross-manager serialization (same process).
# Module state, so it must stay in the module every DbLifecycle is built from.
_GLOBAL_LOCKS: dict[str, asyncio.Lock] = {}


class DbLifecycle(WorldFilesMixin, WorldOpsMixin):
    """Create / load / delete / clean / restore world database files."""

    def __init__(self, host):
        self._host = host
        self._op_lock: asyncio.Lock | None = None

    # ── convenience over the host ────────────────────────────────
    @property
    def _registry(self):
        return self._host.registry

    @property
    def _service(self):
        return self._host._service

    @property
    def _config(self):
        return self._host._config

    # ── serialization ────────────────────────────────────────────
    def _get_locks(self):
        """(global_root_lock, local_manager_lock), created lazily."""
        try:
            root = os.path.abspath(getattr(self._host, "root", "") or os.getcwd())
        except Exception:  # noqa: BLE001
            root = os.getcwd()
        g = _GLOBAL_LOCKS.get(root)
        if g is None:
            g = asyncio.Lock()
            _GLOBAL_LOCKS[root] = g
        if self._op_lock is None:
            self._op_lock = asyncio.Lock()
        return g, self._op_lock

    async def _guarded(self, coro_fn, *args, **kwargs):
        """Run one lifecycle op under global+local locks (fixed order)."""
        g, l = self._get_locks()
        async with g:
            async with l:
                return await coro_fn(*args, **kwargs)

    # ── lifecycle (public, serialized) ───────────────────────────
    async def create(self, name: str) -> dict:
        """Create an EMPTY world (the full schema) and connect to it.

        The fresh world is seeded with the app-template settings (D9) —
        nothing is copied from the world being left.
        """
        return await self._guarded(self._create_unlocked, name)

    async def load(self, path: str, create: bool = False) -> dict:
        """Switch the running world over to another database file."""
        return await self._guarded(self._load_unlocked, path, create)

    async def delete(self, path: str) -> dict:
        """PERMANENTLY delete a world (file + media + every reference).

        Fail-closed phases: validate → scan → switch → detach → database →
        media → finalize. See _delete_unlocked for the full contract.
        """
        return await self._guarded(self._delete_unlocked, path)

    async def clean(self) -> dict:
        """Empty every table, keeping the file (a backup goes to the trash)."""
        return await self._guarded(self._clean_unlocked)

    async def restore_backup(self, backup: str, target: str = "") -> dict:
        """Put a trashed/backed-up file back (the undo half of clean)."""
        return await self._guarded(self._restore_unlocked, backup, target)
