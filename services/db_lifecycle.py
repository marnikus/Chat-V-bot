"""DbLifecycle — the write half of `services.db_service.DbManager` (AREA C).

Owns every MUTATION of the world databases: create, load, delete, clean
and restore_backup, together with the media-reference scans and the
clean-break bookkeeping those operations need. The registry reads (paths,
remembered list, scans, info) live in `services.db_registry.DbRegistry`;
this collaborator calls them through its host.

Every rule from the ONE DB = ONE WORLD design is preserved verbatim
(permanent delete, last-world protection, fail-closed switching, clean
with a trash backup).
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime

from services.db_service import SUFFIXES, db_stem, _media_references

log = logging.getLogger("chatbot")


class DbLifecycle:
    """Create / load / delete / clean / restore world database files."""

    def __init__(self, host):
        self._host = host

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

    # ── lifecycle ────────────────────────────────────────────────
    async def create(self, name: str) -> dict:
        """Create an EMPTY world (the full schema) and connect to it.

        The fresh world is seeded with the app-template settings (D9) —
        nothing is copied from the world being left.
        """
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
        result = await self.load(path, create=True)
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

    async def load(self, path: str, create: bool = False) -> dict:
        """Switch the running world over to another database file."""
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

    async def delete(self, path: str) -> dict:
        """PERMANENTLY delete a world (file + media + every reference).

        Rules (D4/D5 of the design): the last remaining world cannot be
        deleted; deleting the active world switches away first (full world
        restart); the media footprint is computed from the world's own
        `media` rows, and a file is unlinked only when no OTHER existing
        world references it; after the unlink there is nothing left that
        points at the deleted file.
        """
        target = self._registry.resolve(path)
        if not target or not os.path.exists(target):
            return {"ok": False, "error": "that database does not exist"}
        target_abs = os.path.abspath(target)
        existing = [os.path.abspath(p)
                    for p in self._registry.existing_worlds()]
        if len(existing) < 2:
            return {"ok": False,
                    "error": "cannot delete the last database — create a "
                             "new one first",
                    "last_database": True}
        was_active = target_abs == os.path.abspath(
            self._registry.active_path())
        if was_active and self._service is not None:
            fallback = self._pick_fallback(target)
            if not fallback:
                return {"ok": False,
                        "error": "no other database to switch to"}
            # the media footprint must be read BEFORE the world closes
            footprint = await self._world_footprint(target)
            opened = await self.load(fallback)
            if not opened.get("ok"):
                return {"ok": False,
                        "error": opened.get("error", "cannot switch away"),
                        "path": target}
        else:
            footprint = await self._world_footprint(target)
        # every connection that still points at the file must go
        if self._service is not None and \
                os.path.abspath(self._service.db.path) == target_abs:
            try:
                await self._service.detach_db()
            except Exception as exc:                   # noqa: BLE001
                return {"ok": False, "error": str(exc)}
        if self._service is not None and \
                self._service.memory is not None and \
                os.path.abspath(getattr(self._service.memory, "db_path", "")
                                or "") == target_abs:
            try:
                await self._service.memory.close()
            except Exception as exc:                   # noqa: BLE001
                return {"ok": False, "error": str(exc)}
        # ── the unlink ──────────────────────────────────────────
        for suffix in SUFFIXES:
            try:
                if os.path.exists(target + suffix):
                    os.unlink(target + suffix)
            except OSError as exc:
                return {"ok": False,
                        "error": f"the database file is in use: {exc}",
                        "path": target}
        keep = await self._other_references(existing, except_abs=target_abs)
        media_removed = await self._delete_world_media(target, footprint,
                                                       keep)
        # ── clean break: every reference to the world goes with it ─
        self._forget(target)
        if was_active:
            self._persist_path(self._registry.active_path())
        return {"ok": True, "op": "delete", "path": target,
                "was_active": was_active,
                "before_path": target,
                "media_files_removed": media_removed}

    async def _world_footprint(self, path: str) -> set[str]:
        """The world's media: its own folder + the files its rows name."""
        footprint: set[str] = set()
        world_folder = os.path.abspath(self._registry.media_dir(path))
        base = os.path.abspath(self._registry.media_base_dir())
        if world_folder == base or world_folder.startswith(base + os.sep):
            footprint.add(world_folder)
        for ref in await _media_references(path):
            if ref == base:
                continue
            if ref.startswith(base + os.sep):
                footprint.add(ref)
        return footprint

    async def _other_references(self, existing: list[str],
                                except_abs: str = "") -> set[str]:
        """What the OTHER existing worlds point at (read-only scan).

        A scan of a world that cannot be read contributes nothing, so the
        delete proceeds with the conservative rule (a file two worlds share
        is kept, because we could not verify the other world is free of it).
        """
        keep: set[str] = set()
        for world in existing:
            if world == except_abs:
                continue
            keep |= await _media_references(world)
        return keep

    async def _delete_world_media(self, path: str, footprint: set[str],
                                  keep: set[str]) -> int:
        """Remove the world's media bytes, keeping what others reference."""
        removed = 0
        base = os.path.abspath(self._registry.media_base_dir())
        # 1 — the files the world's rows named (reference scan, D2)
        for ref in sorted(footprint):
            if os.path.isdir(ref):
                continue
            if not ref.startswith(base + os.sep):
                continue                     # unknown location — never touch
            if ref in keep:
                continue                     # another world still owns it
            try:
                if os.path.exists(ref):
                    os.unlink(ref)
                    removed += 1
                    # take away folders the unlink left empty
                    folder = os.path.dirname(ref)
                    while folder and folder != base and \
                            folder.startswith(base + os.sep) and \
                            not os.listdir(folder):
                        try:
                            os.rmdir(folder)
                        except OSError:
                            break
                        folder = os.path.dirname(folder)
            except OSError as exc:
                log.debug("cannot remove media file %s: %s", ref, exc)
        # 2 — the world's own folder (exclusive by construction)
        world_folder = os.path.abspath(self._registry.media_dir(path))
        if world_folder.startswith(base + os.sep) and world_folder != base \
                and os.path.isdir(world_folder):
            try:
                shutil.rmtree(world_folder)
            except OSError as exc:
                log.warning("cannot remove world media folder %s: %s",
                            world_folder, exc)
        return removed

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

    async def clean(self) -> dict:
        """Empty every table, keeping the file (a backup goes to the trash).

        Unlike delete, clean is an EDIT of one world: the file backup AND
        the world's own media folder go to `db_trash/`, so Ctrl+Z restores
        the rows and the bytes are preserved next to the backup.
        """
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

    async def restore_backup(self, backup: str, target: str = "") -> dict:
        """Put a trashed/backed-up file back (the undo half of clean)."""
        source = str(backup or "")
        if not source or not os.path.exists(source):
            return {"ok": False, "error": "the backup is gone"}
        destination = self._registry.resolve(target) \
            or self._registry.active_path()
        active = (os.path.abspath(destination) ==
                  os.path.abspath(self._registry.active_path()))
        if active and self._service is not None:
            try:
                await self._service.detach_db()
            except Exception as exc:                   # noqa: BLE001
                return {"ok": False, "error": str(exc)}
        try:
            os.makedirs(os.path.dirname(os.path.abspath(destination)) or ".",
                        exist_ok=True)
            for suffix in SUFFIXES:
                if not os.path.exists(source + suffix):
                    continue
                shutil.copyfile(source + suffix, destination + suffix)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if self._service is not None:
            await self._service.switch_db(destination)
        self._persist_path(destination)
        self._registry._remember(destination)
        return {"ok": True, "path": destination, "backup": source}

    # ── helpers ──────────────────────────────────────────────────
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
