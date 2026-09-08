"""Safe lifecycle for chat archives, never the queue or global undo store.

Create is independent of Load. Validated candidates are opened before a live
swap. Delete/Clean retain SQLite-consistent undo backups in db_trash but no
missing/trash entries appear in the connection panel.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

import aiosqlite

from backend.archive_lock import ArchiveLock
from backend.db_paths import (PROTECTED_DATABASE, canonical_path, in_trash,
                              protected_database, same_database)
from backend.history_db import (HistoryDB, INCOMPATIBLE_SCHEMA, SCHEMA_VERSION,
                                SchemaError, inspect_archive)

log = logging.getLogger("chatbot")
TRASH_DIR = "db_trash"
SUFFIXES = ("", "-wal", "-shm", "-journal")
_SAFE = re.compile(r"[^0-9A-Za-z._-]+")
LAST_DATABASE = "Cannot delete the last database. Create a new one first."
CREATE_SCHEMA_ERROR = "Failed to create database. Schema error."


def mutation(method):
    @wraps(method)
    async def guarded(self, *args, **kwargs):
        async with self._mutations:
            return await method(self, *args, **kwargs)
    return guarded


def safe_db_name(name: str) -> str:
    """A file name the user cannot use to escape the app folder."""
    clean = _SAFE.sub("_", str(name or "").strip()).strip("._-")
    if not clean:
        clean = "history"
    if clean.lower().endswith(".db"):
        clean = clean[:-3]
    return clean[:77] + ".db"


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


class DbManager:
    def __init__(self, config=None, service=None, root: str = ""):
        self._config = config
        self._service = service
        self.root = os.path.abspath(root or os.getcwd())
        self._mutations = ArchiveLock()
        self._offline_lock = ArchiveLock()

    def attach(self, service) -> None:
        self._service = service

    @property
    def service(self):
        return self._service

    @property
    def _archive_lock(self):
        return self.service.db.operation_lock if self.service else self._offline_lock

    def active_path(self) -> str:
        if self.service is not None:
            return os.path.abspath(self.service.db.path)
        stored = self._config.get("history", "db_path", default="history.db") \
            if self._config is not None else "history.db"
        stored = stored if isinstance(stored, str) and stored else "history.db"
        return os.path.abspath(stored if os.path.isabs(stored) else os.path.join(self.root, stored))

    def resolve(self, name_or_path: str) -> str:
        text = str(name_or_path or "").strip()
        if not text:
            return ""
        if os.path.isabs(text):
            return canonical_path(text)
        if os.sep in text or "/" in text:
            return canonical_path(os.path.join(self.root, text))
        return canonical_path(os.path.join(os.path.dirname(self.active_path()), safe_db_name(text)))

    def trash_dir(self) -> str:
        return os.path.join(os.path.dirname(self.active_path()), TRASH_DIR)

    def media_dir(self) -> str:
        if self.service is not None:
            return self.service.media.cache_dir
        media = self._config.get("history", "media", default={}) if self._config else {}
        return str((media or {}).get("cache_dir") or "saved_media")

    def _protected(self, path: str) -> bool:
        return protected_database(path, root=self.root,
                                  memory=getattr(self.service, "memory", None)) or in_trash(path)

    def _eligible(self, path: str) -> bool:
        return not self._protected(path) and inspect_archive(path, full=True)

    # ── discovery / recent files ─────────────────────────────────
    def known_paths(self) -> list[str]:
        raw = self._config.get_state("db_recent", []) if self._config else []
        return [p for p in raw if isinstance(p, str) and p] if isinstance(raw, list) else []

    def _set_recent(self, paths) -> None:
        if self._config is not None and self.known_paths() != paths:
            self._config.set_state(db_recent=paths)

    def _remember(self, path: str) -> None:
        self._set_recent(([canonical_path(path)] + [p for p in self.known_paths()
                            if not same_database(p, path) and self._eligible(p)])[:12])

    def _forget(self, path: str) -> None:
        self._set_recent([p for p in self.known_paths()
                          if not same_database(p, path) and self._eligible(p)])

    def list_dbs(self) -> list[dict]:
        """Only existing chat archives; missing recents are not UI entities."""
        active = self.active_path()
        paths = [active] + self.known_paths()
        folder = os.path.dirname(active)
        try:
            paths += [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                      if n.lower().endswith(".db") and not n.startswith(".cvb-")]
        except OSError as exc:
            log.debug("cannot list archives in %s: %s", folder, exc)
        found = []
        for path in paths:
            path = canonical_path(path)
            if any(same_database(path, old["path"]) for old in found) or not self._eligible(path):
                continue
            found.append({"path": path, "name": os.path.basename(path),
                          "bytes": file_group_size(path), "exists": True,
                          "active": same_database(path, active)})
        self._set_recent([canonical_path(p) for p in self.known_paths()
                          if any(same_database(p, i["path"]) for i in found)])
        for item in found:
            item["can_load"] = not item["active"]
            item["can_delete"] = len(found) > 1
            item["delete_reason"] = "" if item["can_delete"] else LAST_DATABASE
        found.sort(key=lambda i: (not i["active"], i["name"].lower()))
        return found

    async def info(self) -> dict:
        async with self._archive_lock:
            return await self._info()

    async def _info(self) -> dict:
        """Sizes + counts for the DB Connection window."""
        path = self.active_path()
        media_dir = self.media_dir()
        media_bytes, media_files = folder_size(media_dir)
        payload = {
            "path": path,
            "name": os.path.basename(path),
            "exists": os.path.exists(path),
            "db_bytes": file_group_size(path),
            "text_bytes": 0,
            "media_dir": media_dir,
            "media_bytes": media_bytes,
            "media_files": media_files,
            "persons": 0, "messages": 0, "messages_hidden": 0, "media": 0,
            "connected": False,
            "trash_dir": self.trash_dir(),
        }
        service = self._service
        if service is None or not getattr(service.db, "is_open", False):
            payload["total_bytes"] = payload["db_bytes"] + media_bytes
            return payload
        try:
            stats = await service.query.db_stats()
        except Exception as exc:                       # noqa: BLE001
            log.warning("db stats failed: %s", exc)
            payload["error"] = str(exc)
            payload["total_bytes"] = payload["db_bytes"] + media_bytes
            return payload
        payload.update({
            "connected": True,
            "db_bytes": int(stats.get("db_bytes") or payload["db_bytes"]),
            "text_bytes": int(stats.get("text_bytes") or 0),
            "persons": int(stats.get("persons") or 0),
            "persons_deleted": int(stats.get("persons_deleted") or 0),
            "messages": int(stats.get("messages") or 0),
            "messages_hidden": int(stats.get("messages_hidden") or 0),
            "media": int(stats.get("media") or 0),
            "media_cached": int(stats.get("media_cached") or 0),
            "fts": bool(stats.get("fts")),
        })
        payload["total_bytes"] = payload["db_bytes"] + media_bytes
        return payload

    # ── lifecycle ────────────────────────────────────────────────
    def _new_db(self, path: str) -> HistoryDB:
        use_fts = bool(self.service.settings().get("use_fts", True)) if self.service else True
        return HistoryDB(path, use_fts=use_fts)

    @staticmethod
    def _stage(folder: str) -> str:
        fd, path = tempfile.mkstemp(prefix=".cvb-", suffix=".db", dir=folder)
        os.close(fd)
        return path

    @staticmethod
    def _remove_owned(path: str) -> None:
        if not path:
            return
        for suffix in SUFFIXES:
            try:
                os.unlink(path + suffix)
            except FileNotFoundError:
                pass

    @staticmethod
    def _publish(stage: str, destination: str) -> None:
        # Same-folder hardlink is atomic and refuses overwrite even if another
        # creator wins after the initial existence check (also on NTFS).
        os.link(stage, destination)
        os.unlink(stage)

    @mutation
    async def create(self, name: str) -> dict:
        """Initialize an independent file. NEVER touch the active pipeline."""
        path = self.resolve(name)
        if not path:
            return {"ok": False, "error": "give the database a name"}
        if self._protected(path):
            return {"ok": False, "error": PROTECTED_DATABASE}
        if any(os.path.lexists(path + s) for s in SUFFIXES):
            return {"ok": False, "error": f"{os.path.basename(path)} already exists"}
        before = self.active_path()
        stage, fresh = "", None
        phase = "file"
        try:
            folder = os.path.dirname(path)
            os.makedirs(folder, exist_ok=True)
            stage = self._stage(folder)
            fresh = self._new_db(stage)
            phase = "schema"
            await fresh.init()
            await fresh.validate()
            await fresh.close()  # checkpoint all WAL content before publishing
            phase = "publish"
            self._publish(stage, path)
            self._remember(path)
            return {"ok": True, "op": "create", "path": path,
                    "before_path": before, "path_after": before,
                    "active_changed": False, "schema_version": SCHEMA_VERSION}
        except Exception as exc:
            detail = getattr(exc, "detail", str(exc))
            log.warning("create %s failed (%s): %s", path, phase, detail)
            error = CREATE_SCHEMA_ERROR if phase == "schema" else str(exc)
            return {"ok": False, "error": error, "detail": detail}
        finally:
            if fresh is not None:
                await fresh.close()
            self._remove_owned(stage)

    @mutation
    async def load(self, path: str) -> dict:
        target = self.resolve(path)
        if not target:
            return {"ok": False, "error": "no database selected"}
        if self._protected(target):
            return {"ok": False, "error": PROTECTED_DATABASE}
        if not os.path.isfile(target):
            return {"ok": False, "error": f"{target} does not exist"}
        before = self.active_path()
        fresh = None
        try:
            if self.service is not None:
                await self.service.switch_db(target)
            else:
                fresh = self._new_db(target)
                await fresh.init(allow_create=False)
                self._persist_path(target)
        except Exception as exc:
            detail = getattr(exc, "detail", str(exc))
            log.warning("load %s refused: %s", target, detail)
            return {"ok": False, "error": INCOMPATIBLE_SCHEMA, "detail": detail, "path": target}
        finally:
            if fresh is not None:
                await fresh.close()
        self._remember(target)
        unchanged = same_database(target, before)
        return {"ok": True, "op": "load", "path": target, "before_path": before,
                "path_after": target, "unchanged": unchanged,
                "active_changed": not unchanged}

    @mutation
    async def delete(self, path: str) -> dict:
        async with self._archive_lock:
            target = self.resolve(path)
            if not target or not os.path.isfile(target):
                if target:
                    self._forget(target)
                return {"ok": False, "error": "that database does not exist"}
            if self._protected(target):
                return {"ok": False, "error": PROTECTED_DATABASE}
            if not self._eligible(target):
                return {"ok": False, "error": INCOMPATIBLE_SCHEMA}
            before = self.active_path()
            was_active = same_database(target, before)
            alternatives = [i["path"] for i in self.list_dbs()
                            if not same_database(i["path"], target)]
            if not alternatives:
                return {"ok": False, "error": LAST_DATABASE}
            if was_active:
                for fallback in alternatives:
                    opened = await self.load(fallback)
                    if opened.get("ok"):
                        break
                else:
                    return {"ok": False, "error": LAST_DATABASE,
                            "detail": "No other database passed activation validation."}
            backup = self._move_to_trash(target)
            if not backup:
                if was_active:
                    await self.load(before)
                return {"ok": False, "error": "the database file is in use"}
            self._forget(target)
            return {"ok": True, "op": "delete", "path": target, "backup": backup,
                    "was_active": was_active, "before_path": before,
                    "path_after": self.active_path(), "active_changed": was_active}

    @mutation
    async def clean(self) -> dict:
        if self.service is None:
            return {"ok": False, "error": "the message archive is not running"}
        async with self._archive_lock:
            path = self.active_path()
            if self._protected(path):
                return {"ok": False, "error": PROTECTED_DATABASE}
            db = self.service.db
            backup = ""
            removed = {}
            try:
                await db.validate()
                await db.commit()
                backup = await self._copy_to_trash(path, tag="clean")
                if not backup:
                    return {"ok": False, "error": "Cannot clean database: backup failed."}
                await db.execute("BEGIN IMMEDIATE")
                for table in ("messages", "cursors", "gaps", "media", "persons"):
                    removed[table] = int(await db.scalar(f"SELECT COUNT(*) FROM {table}"))
                    await db.execute(f"DELETE FROM {table}")
                await db.execute("DELETE FROM sqlite_sequence")
                await db.commit()
            except BaseException as exc:
                await db.conn.rollback()
                if not isinstance(exc, Exception):
                    raise
                log.warning("clean failed: %s", getattr(exc, "detail", str(exc)))
                return {"ok": False, "error": str(exc), "backup": backup}
            self.service.collector.reset_state()
            self.service.generation += 1
            # Compaction is optional; failure cannot undo a committed clean.
            try:
                await db.execute("VACUUM")
            except Exception as exc:
                log.warning("database cleaned, compaction skipped: %s", exc)
            return {"ok": True, "op": "clean", "path": path, "backup": backup,
                    "removed": removed, "before_path": path, "active_changed": True}

    @mutation
    async def restore_backup(self, backup: str, target: str = "", *, activate: bool = False) -> dict:
        """Validate a snapshot before restoration; inactive restores stay inactive."""
        source = str(backup or "")
        destination = self.resolve(target) or self.active_path()
        if self._protected(destination):
            return {"ok": False, "error": PROTECTED_DATABASE}
        if not source or not os.path.isfile(source):
            return {"ok": False, "error": "the backup is gone"}
        if not in_trash(source) or not inspect_archive(source):
            return {"ok": False, "error": INCOMPATIBLE_SCHEMA}
        stage, candidate, displaced = "", None, ""
        async with self._archive_lock:
            before = self.active_path()
            active = same_database(destination, before)
            if os.path.exists(destination) and not self._eligible(destination):
                return {"ok": False, "error": INCOMPATIBLE_SCHEMA}
            try:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                stage = self._stage(os.path.dirname(destination))
                # Old backups can carry WAL siblings. SQLite reads a consistent
                # snapshot; copying just the main file would lose those rows.
                reader = await aiosqlite.connect(Path(os.path.abspath(source)).as_uri() + "?mode=ro", uri=True)
                try:
                    writer = await aiosqlite.connect(stage)
                    try:
                        await reader.backup(writer)
                    finally:
                        await writer.close()
                finally:
                    await reader.close()
                candidate = self._new_db(stage)
                await candidate.init(allow_create=False)
                if active and self.service is not None:
                    # SQLite's backup transaction replaces contents atomically,
                    # with no close/unlink window (important on Windows).
                    safety = await self._copy_to_trash(destination, tag="restore")
                    if not safety:
                        return {"ok": False, "error": "Cannot restore database: backup failed."}
                    await candidate.conn.backup(self.service.db.conn)
                    self.service.db.fts_enabled = candidate.fts_enabled
                    self.service.collector.reset_state()
                    self.service.generation += 1
                else:
                    await candidate.close()
                    if os.path.exists(destination):
                        displaced = self._move_to_trash(destination)
                        if not displaced:
                            return {"ok": False, "error": "the database file is in use"}
                    try:
                        self._publish(stage, destination)
                    except BaseException:
                        if displaced:
                            self._move_group(displaced, destination)
                        raise
                self._remember(destination)
                if activate and not active:
                    opened = await self.load(destination)
                    if not opened.get("ok"):
                        return opened
                return {"ok": True, "path": destination, "backup": source,
                        "before_path": before, "path_after": self.active_path(),
                        "active_changed": active or activate}
            except Exception as exc:
                log.warning("restore failed: %s", getattr(exc, "detail", str(exc)))
                return {"ok": False, "error": str(exc)}
            finally:
                if candidate is not None:
                    await candidate.close()
                self._remove_owned(stage)

    # ── backups / config ─────────────────────────────────────────
    def _persist_path(self, path: str) -> None:
        if self._config is None:
            return
        history = self._config.get("history", default={}) or {}
        history = dict(history) if isinstance(history, dict) else {}
        history["db_path"] = path
        self._config.set("history", history)
        self._config.save()

    def _stamp(self, tag: str, name: str) -> str:
        return f"{datetime.now():%Y%m%d-%H%M%S}_{tag}_{uuid.uuid4().hex[:12]}_{name}"

    @staticmethod
    def _move_group(source: str, destination: str) -> None:
        moved = []
        try:
            for suffix in SUFFIXES:
                if os.path.exists(source + suffix):
                    os.rename(source + suffix, destination + suffix)
                    moved.append(suffix)
        except OSError:
            for suffix in reversed(moved):
                os.rename(destination + suffix, source + suffix)
            raise

    def _move_to_trash(self, path: str) -> str:
        trash = self.trash_dir()
        try:
            os.makedirs(trash, exist_ok=True)
            target = os.path.join(trash, self._stamp("deleted", os.path.basename(path)))
            self._move_group(path, target)
            return target
        except OSError as exc:
            log.warning("cannot trash %s: %s", path, exc)
            return ""

    async def _copy_to_trash(self, path: str, tag: str = "backup") -> str:
        target = ""
        try:
            os.makedirs(self.trash_dir(), exist_ok=True)
            target = os.path.join(self.trash_dir(), self._stamp(tag, os.path.basename(path)))
            await self.service.db.backup_to(target)
            return target
        except BaseException as exc:
            self._remove_owned(target)
            if not isinstance(exc, Exception):
                raise
            log.warning("cannot back up %s: %s", path, exc)
            return ""
