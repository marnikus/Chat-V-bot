"""The five unlocked world operations (Round H step H-C3).

`DbLifecycle` serializes every mutation through `_guarded`; this mixin holds
what each operation actually does once the locks are held — create, load,
delete, clean and restore — plus the detach step a restore needs when its
target is the live world.

Split from `services/db_lifecycle.py` by operation, which is the vocabulary
the class already used (`_create_unlocked` … `_restore_unlocked`), so the
public surface and every `lifecycle._*_unlocked(...)` caller — including
`services/db_deletion_flow*.py` and the safety-deletion tests — are unchanged.

Import direction: `services.db_deletion_flow` is imported *inside*
`_delete_unlocked` to keep the module import graph exactly as it was
(`db_service` imports the lifecycle lazily).
"""

from __future__ import annotations

import logging
import os
import shutil

from services.db_service import db_stem

from .db_lifecycle_files import copy_backup_trio

log = logging.getLogger("chatbot")


class WorldOpsMixin:
    """Create / load / delete / clean / restore, unlocked; on ``DbLifecycle``."""

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
            await self._seed_new_world(path)
        return result

    async def _seed_new_world(self, path: str) -> None:
        """Seed the app-template settings into a freshly created world (D9).

        A failure is a warning, not a failed create: the world exists and is
        connected, it just has no seeded settings yet (RULE 4 — report the
        difference instead of failing the operation that did work).
        """
        if self._service is None:
            return
        try:
            await self._service.seed_app_settings()
        except Exception as exc:                           # noqa: BLE001
            log.warning("could not seed settings into %s: %s",
                        os.path.basename(path), exc)

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
        except Exception as exc:                           # noqa: BLE001
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

    async def _clean_unlocked(self) -> dict:
        """Empty every table, keeping the file (a backup goes to the trash)."""
        path = self._registry.active_path()
        if self._service is None:
            return {"ok": False, "error": "the message archive is not running"}
        backup = self._copy_to_trash(path, tag="clean")
        try:
            removed = await self._empty_tables(self._service.db)
        except Exception as exc:                           # noqa: BLE001
            log.warning("clean failed: %s", exc)
            return {"ok": False, "error": str(exc), "backup": backup}
        return {"ok": True, "op": "clean", "path": path, "backup": backup,
                "removed": removed, "before_path": path,
                "media_moved": self._trash_world_media(path)}

    async def _empty_tables(self, db) -> dict:
        """DELETE every content table; return the row counts removed.

        Raises on the first failure — `_clean_unlocked` turns that into the
        fail-closed `{"ok": False, "backup": …}` result, so a half-emptied
        world is never reported as cleaned.
        """
        removed = {}
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
            except Exception:                              # noqa: BLE001
                pass
        await db.commit()
        await db.execute("VACUUM")
        await db.commit()
        return removed

    def _trash_world_media(self, path: str) -> str:
        """Move this world's media folder to the trash.

        Returns the intended destination, including when the move itself
        failed — the pre-split code assigned the name before calling
        `shutil.move`, and the reported shape is pinned by the deletion
        tests, so the oddity is preserved rather than silently changed.
        An empty string means the folder was outside the media root (nothing
        to move), which is a different fact from a failed move.
        """
        world_folder = os.path.abspath(self._registry.media_dir(path))
        base = os.path.abspath(self._registry.media_base_dir())
        inside = (world_folder.startswith(base + os.sep)
                  and world_folder != base and os.path.isdir(world_folder))
        if not inside:
            return ""
        target = os.path.join(self._registry.trash_dir(),
                              self._stamp("clean_media", db_stem(path)))
        try:
            shutil.move(world_folder, target)
        except OSError as exc:
            log.warning("cannot move world media to trash: %s", exc)
        return target

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
        err = copy_backup_trio(source, destination)
        if err is not None:
            return err
        if self._service is not None:
            await self._service.switch_db(destination)
        self._persist_path(destination)
        self._registry._remember(destination)
        return {"ok": True, "path": destination, "backup": source}

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
        except Exception as exc:                           # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return None
