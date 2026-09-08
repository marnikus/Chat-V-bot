"""Create / load / delete / clean the message-archive database.

The DB Connection window drives this module. Two promises shape it:

* **nothing is ever unlinked.** "Delete DB" and "Clean DB" move the file (and
  its `-wal`/`-shm` siblings) into `db_trash/` first, so both operations are
  reversible with one Ctrl+Z, exactly like every other editable surface
  (AGENT_RULES RULE 12).
* **a failed swap leaves the app connected.** Switching databases closes the
  live connection, and if the new file cannot be opened the previous one is
  re-opened before the error is reported (fail closed).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime

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
    """Lifecycle + size reporting for the archive database file."""

    def __init__(self, config=None, service=None, root: str = ""):
        self._config = config
        self._service = service
        self.root = root or os.getcwd()

    # ── wiring ───────────────────────────────────────────────────
    def attach(self, service) -> None:
        self._service = service

    @property
    def service(self):
        return self._service

    # ── paths ────────────────────────────────────────────────────
    def active_path(self) -> str:
        if self._service is not None:
            try:
                return self._service.db.path
            except Exception:                          # noqa: BLE001
                pass
        if self._config is not None:
            stored = self._config.get("history", "db_path", default="history.db")
            if isinstance(stored, str) and stored:
                return stored
        return "history.db"

    def resolve(self, name_or_path: str) -> str:
        """Absolute-ish path for a user-supplied name (kept inside the app)."""
        text = str(name_or_path or "").strip()
        if not text:
            return ""
        if os.path.isabs(text) or os.sep in text or "/" in text:
            return os.path.normpath(text)
        return os.path.join(os.path.dirname(self.active_path()) or ".",
                            safe_db_name(text))

    def trash_dir(self) -> str:
        base = os.path.dirname(os.path.abspath(self.active_path())) or self.root
        return os.path.join(base, TRASH_DIR)

    def media_dir(self) -> str:
        if self._service is not None:
            try:
                return self._service.media.cache_dir
            except Exception:                          # noqa: BLE001
                pass
        if self._config is not None:
            media = self._config.get("history", "media", default={}) or {}
            if isinstance(media, dict):
                return str(media.get("cache_dir") or "saved_media")
        return "saved_media"

    # ── listing ──────────────────────────────────────────────────
    def known_paths(self) -> list[str]:
        stored = []
        if self._config is not None:
            raw = self._config.get_state("db_recent", [])
            if isinstance(raw, list):
                stored = [p for p in raw if isinstance(p, str) and p]
        return stored

    def _remember(self, path: str) -> None:
        if self._config is None or not path:
            return
        recent = [p for p in self.known_paths() if p != path]
        recent.insert(0, path)
        self._config.set_state(db_recent=recent[:12])

    def list_dbs(self) -> list[dict]:
        """Every `*.db` next to the active file, plus remembered paths."""
        active = self.active_path()
        folder = os.path.dirname(os.path.abspath(active)) or self.root
        found: dict[str, dict] = {}
        try:
            for name in sorted(os.listdir(folder)):
                if not name.lower().endswith(".db"):
                    continue
                path = os.path.join(folder, name)
                found[os.path.abspath(path)] = {
                    "path": path, "name": name,
                    "bytes": file_group_size(path),
                    "exists": True,
                }
        except OSError as exc:
            log.debug("cannot list databases in %s: %s", folder, exc)
        for path in [active] + self.known_paths():
            key = os.path.abspath(path)
            if key in found:
                continue
            found[key] = {"path": path, "name": os.path.basename(path),
                          "bytes": file_group_size(path),
                          "exists": os.path.exists(path)}
        items = list(found.values())
        for item in items:
            item["active"] = (os.path.abspath(item["path"]) ==
                              os.path.abspath(active))
        items.sort(key=lambda i: (not i["active"], i["name"].lower()))
        return items

    # ── info ─────────────────────────────────────────────────────
    async def info(self) -> dict:
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
    async def create(self, name: str) -> dict:
        """Create an EMPTY database and connect to it."""
        path = self.resolve(name)
        if not path:
            return {"ok": False, "error": "give the database a name"}
        if os.path.exists(path):
            return {"ok": False, "error": f"{os.path.basename(path)} already exists"}
        before = self.active_path()
        folder = os.path.dirname(os.path.abspath(path))
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        result = await self.load(path, create=True)
        if result.get("ok"):
            result["op"] = "create"
            result["before_path"] = before
        return result

    async def load(self, path: str, create: bool = False) -> dict:
        """Switch the running archive over to another database file."""
        target = self.resolve(path)
        if not target:
            return {"ok": False, "error": "no database selected"}
        if not create and not os.path.exists(target):
            return {"ok": False, "error": f"{target} does not exist"}
        before = self.active_path()
        if os.path.abspath(target) == os.path.abspath(before) and not create:
            return {"ok": True, "op": "load", "path": target,
                    "before_path": before, "unchanged": True}
        if self._service is None:
            self._persist_path(target)
            self._remember(target)
            return {"ok": True, "op": "load", "path": target,
                    "before_path": before, "offline": True}
        try:
            await self._service.switch_db(target)
        except Exception as exc:                       # noqa: BLE001
            log.warning("switching to %s failed: %s", target, exc)
            return {"ok": False, "error": str(exc), "path": target}
        self._persist_path(target)
        self._remember(target)
        return {"ok": True, "op": "load", "path": target, "before_path": before}

    async def delete(self, path: str) -> dict:
        """Move a database into `db_trash/` (never unlink) and switch away."""
        target = self.resolve(path)
        if not target or not os.path.exists(target):
            return {"ok": False, "error": "that database does not exist"}
        was_active = (os.path.abspath(target) ==
                      os.path.abspath(self.active_path()))
        fallback = ""
        if was_active:
            fallback = self._pick_fallback(target)
            if self._service is not None:
                try:
                    await self._service.detach_db()
                except Exception as exc:               # noqa: BLE001
                    return {"ok": False, "error": str(exc)}
        backup = self._move_to_trash(target)
        if not backup:
            if was_active and self._service is not None:
                await self._service.switch_db(target)
            return {"ok": False, "error": "the database file is in use"}
        result = {"ok": True, "op": "delete", "path": target, "backup": backup,
                  "was_active": was_active, "before_path": target}
        if was_active:
            opened = await self.load(fallback, create=not os.path.exists(fallback))
            result["path_after"] = opened.get("path", fallback)
            if not opened.get("ok"):
                result["error"] = opened.get("error", "")
        return result

    async def clean(self) -> dict:
        """Empty every table, keeping the file (a backup goes to the trash)."""
        path = self.active_path()
        if self._service is None:
            return {"ok": False, "error": "the message archive is not running"}
        backup = self._copy_to_trash(path, tag="clean")
        db = self._service.db
        removed = {}
        try:
            for table in ("messages", "media", "cursors", "gaps", "persons"):
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
        return {"ok": True, "op": "clean", "path": path, "backup": backup,
                "removed": removed, "before_path": path}

    async def restore_backup(self, backup: str, target: str = "") -> dict:
        """Put a trashed/backed-up file back (the undo half of delete/clean)."""
        source = str(backup or "")
        if not source or not os.path.exists(source):
            return {"ok": False, "error": "the backup is gone"}
        destination = self.resolve(target) or self.active_path()
        active = (os.path.abspath(destination) ==
                  os.path.abspath(self.active_path()))
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
        for item in self.list_dbs():
            if (os.path.abspath(item["path"]) != os.path.abspath(deleted)
                    and item.get("exists")):
                return item["path"]
        folder = os.path.dirname(os.path.abspath(deleted)) or self.root
        return os.path.join(folder, "history.db")

    def _stamp(self, tag: str, name: str) -> str:
        return (f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{tag}_{name}")

    def _move_to_trash(self, path: str) -> str:
        trash = self.trash_dir()
        try:
            os.makedirs(trash, exist_ok=True)
            target = os.path.join(trash,
                                  self._stamp("deleted", os.path.basename(path)))
            for suffix in SUFFIXES:
                if os.path.exists(path + suffix):
                    shutil.move(path + suffix, target + suffix)
            return target
        except OSError as exc:
            log.warning("cannot trash %s: %s", path, exc)
            return ""

    def _copy_to_trash(self, path: str, tag: str = "backup") -> str:
        trash = self.trash_dir()
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
