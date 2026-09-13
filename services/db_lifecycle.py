"""DbLifecycle — the write half of `services.db_service.DbManager` (AREA C).

Owns every MUTATION of the world databases: create, load, delete, clean
and restore_backup, together with the media-reference scans and the
clean-break bookkeeping those operations need. The registry reads (paths,
remembered list, scans, info) live in `services.db_registry.DbRegistry`;
this collaborator calls them through its host.

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
import shutil
from datetime import datetime

from services.db_service import SUFFIXES, db_stem

log = logging.getLogger("chatbot")


def _copy_backup_trio(source: str, destination: str) -> dict | None:
    """Copy a backup's db+wal+shm into place; an err-dict when that failed.

    Module-level because it is a pure filesystem move between two paths —
    it reads nothing from the lifecycle object.
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(destination)) or ".",
                    exist_ok=True)
        for suffix in SUFFIXES:
            if not os.path.exists(source + suffix):
                continue
            shutil.copyfile(source + suffix, destination + suffix)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return None

# Root-keyed global locks for cross-manager serialization (same process).
_GLOBAL_LOCKS: dict[str, asyncio.Lock] = {}


class DbLifecycle:
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

    # ── unlocked delegates (internal; delete calls _load_unlocked) ─
    async def _create_unlocked(self, name: str) -> dict:
        path = self._registry.resolve(name)
        if not path:
            if str(name or "").strip():
                return {"ok": False,
                        "error": "the database must stay inside the app folder"}
            return {"ok": False, "error": "give the database a name"}
        if os.path.exists(path):
            return {"ok": False, "error": f"{os.path.basename(path)} already exists"}
        before = self._registry.active_path()
        folder = os.path.dirname(os.path.abspath(path))
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        result = await self._load_unlocked(path, create=True)
        if result.get("ok"):
            result["op"] = "create"
            result["before_path"] = before
            if self._service is not None:
                try:
                    await self._service.seed_app_settings()
                except Exception as exc:               # noqa: BLE001
                    log.warning("could not seed settings into %s: %s",
                                os.path.basename(path), exc)
        return result

    async def _load_unlocked(self, path: str, create: bool = False) -> dict:
        target = self._registry.resolve(path)
        if not target:
            return {"ok": False, "error": "no database selected"}
        if not create and not os.path.exists(target):
            return {"ok": False, "error": f"{target} does not exist"}
        before = self._registry.active_path()
        if os.path.abspath(target) == os.path.abspath(before) and not create:
            return {"ok": True, "op": "load", "path": target,
                    "before_path": before, "unchanged": True}
        if self._service is None:
            self._persist_path(target)
            self._registry._remember(target)
            return {"ok": True, "op": "load", "path": target,
                    "before_path": before, "offline": True}
        try:
            await self._service.switch_db(target)
        except Exception as exc:                       # noqa: BLE001
            log.warning("switching to %s failed: %s", target, exc)
            return {"ok": False, "error": str(exc), "path": target}
        self._persist_path(target)
        self._registry._remember(target)
        return {"ok": True, "op": "load", "path": target, "before_path": before}

    async def _delete_unlocked(self, path: str) -> dict:
        """Fail-closed permanent deletion with truthful partial results.

        Contract (master plan §3.2): ok only when fully completed; phase in
        validate/scan/switch/detach/database/media/finalize; partial True when
        some irreversible work happened but not all; world_changed distinct
        from partial; active_path observed; removed/retained/failed exact;
        media_files_removed counts actual unlinks.

        The read-only scan phase lives in `services.db_deletion_scan` and
        the mutating phases in `services.db_deletion_flow` (one small
        function per phase); this delegate stays thin so the irreversible
        path is not one large, untestable method.
        """
        # function-local import: keeps the module import graph identical to
        # the previous inline version (db_service imports lifecycle lazily).
        from services.db_deletion_flow import delete_world
        return await delete_world(self, path)

    def _forget(self, path: str) -> None:
        """Clean break: no reference to the deleted file survives."""
        self._registry._prune_remembered()
        if self._config is None:
            return
        stored = self._config.get("history", "db_path", default="")
        if isinstance(stored, str) and \
                os.path.abspath(stored) == os.path.abspath(path):
            replacement = self._registry.active_path()
            if replacement and os.path.exists(replacement) and \
                    os.path.abspath(replacement) != os.path.abspath(path):
                history = self._config.get("history", default={}) or {}
                if not isinstance(history, dict):
                    history = {}
                history = dict(history)
                history["db_path"] = replacement
                self._config.set("history", history)
                self._config.save()

    async def _clean_unlocked(self) -> dict:
        """Empty every table, keeping the file (a backup goes to the trash)."""
        path = self._registry.active_path()
        if self._service is None:
            return {"ok": False, "error": "the message archive is not running"}
        backup = self._copy_to_trash(path, tag="clean")
        db = self._service.db
        removed = {}
        try:
            for table in ("messages", "media", "cursors", "gaps", "persons",
                          "users"):
                removed[table] = int(await db.scalar(
                    f"SELECT COUNT(*) FROM {table}", (), 0))
                await db.execute(f"DELETE FROM {table}")
            await db.execute("DELETE FROM sqlite_sequence")
            if db.fts_enabled:
                try:
                    await db.execute(
                        "INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
                except Exception:                      # noqa: BLE001
                    pass
            await db.commit()
            await db.execute("VACUUM")
            await db.commit()
        except Exception as exc:                       # noqa: BLE001
            log.warning("clean failed: %s", exc)
            return {"ok": False, "error": str(exc), "backup": backup}
        media_moved = ""
        world_folder = os.path.abspath(self._registry.media_dir(path))
        base = os.path.abspath(self._registry.media_base_dir())
        if world_folder.startswith(base + os.sep) and world_folder != base \
                and os.path.isdir(world_folder):
            try:
                media_moved = os.path.join(
                    self._registry.trash_dir(),
                    self._stamp("clean_media", db_stem(path)))
                shutil.move(world_folder, media_moved)
            except OSError as exc:
                log.warning("cannot move world media to trash: %s", exc)
        return {"ok": True, "op": "clean", "path": path, "backup": backup,
                "removed": removed, "before_path": path,
                "media_moved": media_moved}

    async def _restore_unlocked(self, backup: str, target: str = "") -> dict:
        """Put a trashed/backed-up file back (the undo half of clean)."""
        source = str(backup or "")
        if not source or not os.path.exists(source):
            return {"ok": False, "error": "the backup is gone"}
        destination = self._registry.resolve(target) \
            or self._registry.active_path()
        err = await self._detach_if_active(destination)
        if err is not None:
            return err
        err = _copy_backup_trio(source, destination)
        if err is not None:
            return err
        if self._service is not None:
            await self._service.switch_db(destination)
        self._persist_path(destination)
        self._registry._remember(destination)
        return {"ok": True, "path": destination, "backup": source}

    # ── helpers ──────────────────────────────────────────────────
    async def _detach_if_active(self, destination: str) -> dict | None:
        """Detach the live world when the restore target IS it.

        Returns an err-dict when detaching failed (the restore must then
        stop, fail-closed), and None both when there was nothing to detach
        and when the detach worked.
        """
        active = (os.path.abspath(destination) ==
                  os.path.abspath(self._registry.active_path()))
        if not (active and self._service is not None):
            return None
        try:
            await self._service.detach_db()
        except Exception as exc:                       # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return None

    def _persist_path(self, path: str) -> None:
        if self._config is None:
            return
        history = self._config.get("history", default={}) or {}
        if not isinstance(history, dict):
            history = {}
        history = dict(history)
        history["db_path"] = path
        self._config.set("history", history)
        self._config.save()

    def _pick_fallback(self, deleted: str) -> str:
        """Which database to open after the active one is deleted."""
        for item in self._registry.list_dbs():
            if (os.path.abspath(item["path"]) != os.path.abspath(deleted)
                    and item.get("exists")):
                return item["path"]
        return ""

    def _stamp(self, tag: str, name: str) -> str:
        return (f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{tag}_{name}")

    def _copy_to_trash(self, path: str, tag: str = "backup") -> str:
        trash = self._registry.trash_dir()
        try:
            os.makedirs(trash, exist_ok=True)
            target = os.path.join(trash,
                                  self._stamp(tag, os.path.basename(path)))
            for suffix in SUFFIXES:
                if os.path.exists(path + suffix):
                    shutil.copyfile(path + suffix, target + suffix)
            return target
        except OSError as exc:
            log.warning("cannot back up %s: %s", path, exc)
            return ""
