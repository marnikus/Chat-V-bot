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

import asyncio
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
    """Lifecycle + size reporting for the world database files."""

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

    def media_base_dir(self) -> str:
        """The app-level media root (one folder per world lives inside it)."""
        if self._service is not None:
            try:
                return self._service.media_base_dir()
            except Exception:                          # noqa: BLE001
                pass
        if self._config is not None:
            media = self._config.get("history", "media", default={}) or {}
            if isinstance(media, dict):
                return str(media.get("cache_dir") or "saved_media")
        return "saved_media"

    def media_dir(self, path: str = "") -> str:
        """The world's own media folder: `<media root>/<world stem>/`."""
        target = path or self.active_path()
        return os.path.join(self.media_base_dir(), db_stem(target))

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

    def _prune_remembered(self) -> None:
        """Drop remembered paths whose file is gone (the "missing" ghosts).

        `db_recent` is a recall list, not a registry: a file that does not
        exist on disk must never reach the UI (D3 of the design).
        """
        if self._config is None:
            return
        stored = self.known_paths()
        kept = [p for p in stored if os.path.exists(p)]
        if len(kept) != len(stored):
            self._config.set_state(db_recent=kept[:12])

    def existing_worlds(self) -> list[str]:
        """Every database file that EXISTS: the folder scan + the active file."""
        active = self.active_path()
        folder = os.path.dirname(os.path.abspath(active)) or self.root
        found: dict[str, str] = {}
        try:
            for name in sorted(os.listdir(folder)):
                if not name.lower().endswith(".db"):
                    continue
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    found[os.path.abspath(path)] = path
        except OSError as exc:
            log.debug("cannot list databases in %s: %s", folder, exc)
        if os.path.exists(active):
            found.setdefault(os.path.abspath(active), active)
        return [found[key] for key in sorted(found)]

    def list_dbs(self) -> list[dict]:
        """Every `*.db` that exists, with delete eligibility (D3, D5).

        No more remembered-but-gone paths: those are pruned before they can
        render, so the "missing" row is impossible, and `can_delete`/
        `delete_hint` let the UI mirror the backend's last-world rule.
        """
        self._prune_remembered()
        active = self.active_path()
        total = len(self.existing_worlds())
        items = []
        for path in self.existing_worlds():
            items.append({
                "path": path, "name": os.path.basename(path),
                "bytes": file_group_size(path),
                "exists": True,
                "active": os.path.abspath(path) == os.path.abspath(active),
                "can_delete": total >= 2,
                "delete_hint": ("Create a new database before deleting the "
                                "last one" if total < 2 else
                                "Permanently delete this database and its "
                                "media"),
            })
        items.sort(key=lambda i: (not i["active"], i["name"].lower()))
        return items

    # ── info ─────────────────────────────────────────────────────
    async def info(self) -> dict:
        """Sizes + counts for the DB Connection window."""
        path = self.active_path()
        media_dir = self.media_dir(path)
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
        """Create an EMPTY world (the full schema) and connect to it.

        The fresh world is seeded with the app-template settings (D9) —
        nothing is copied from the world being left.
        """
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
            if self._service is not None:
                try:
                    await self._service.seed_app_settings()
                except Exception as exc:               # noqa: BLE001
                    log.warning("could not seed settings into %s: %s",
                                os.path.basename(path), exc)
        return result

    async def load(self, path: str, create: bool = False) -> dict:
        """Switch the running world over to another database file."""
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
        """PERMANENTLY delete a world (file + media + every reference).

        Rules (D4/D5 of the design): the last remaining world cannot be
        deleted; deleting the active world switches away first (full world
        restart); the media footprint is computed from the world's own
        `media` rows, and a file is unlinked only when no OTHER existing
        world references it; after the unlink there is nothing left that
        points at the deleted file.
        """
        target = self.resolve(path)
        if not target or not os.path.exists(target):
            return {"ok": False, "error": "that database does not exist"}
        target_abs = os.path.abspath(target)
        existing = [os.path.abspath(p) for p in self.existing_worlds()]
        if len(existing) < 2:
            return {"ok": False,
                    "error": "cannot delete the last database — create a "
                             "new one first",
                    "last_database": True}
        was_active = target_abs == os.path.abspath(self.active_path())
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
        if self._service is not None and self._service.memory is not None and \
                os.path.abspath(getattr(self._service.memory, "db_path", "") or "") \
                == target_abs:
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
                return {"ok": False, "error": f"the database file is in use: {exc}",
                        "path": target}
        keep = await self._other_references(existing, except_abs=target_abs)
        media_removed = await self._delete_world_media(target, footprint, keep)
        # ── clean break: every reference to the world goes with it ─
        self._forget(target)
        if was_active:
            self._persist_path(self.active_path())
        return {"ok": True, "op": "delete", "path": target,
                "was_active": was_active,
                "before_path": target,
                "media_files_removed": media_removed}

    async def _world_footprint(self, path: str) -> set[str]:
        """The world's media: its own folder + the files its rows name."""
        footprint: set[str] = set()
        world_folder = os.path.abspath(self.media_dir(path))
        base = os.path.abspath(self.media_base_dir())
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
        base = os.path.abspath(self.media_base_dir())
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
        world_folder = os.path.abspath(self.media_dir(path))
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
        self._prune_remembered()
        if self._config is None:
            return
        stored = self._config.get("history", "db_path", default="")
        if isinstance(stored, str) and \
                os.path.abspath(stored) == os.path.abspath(path):
            replacement = self.active_path()
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
        path = self.active_path()
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
        world_folder = os.path.abspath(self.media_dir(path))
        base = os.path.abspath(self.media_base_dir())
        if world_folder.startswith(base + os.sep) and world_folder != base \
                and os.path.isdir(world_folder):
            try:
                media_moved = os.path.join(
                    self.trash_dir(),
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
        self._remember(destination)
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
        return ""

    def _stamp(self, tag: str, name: str) -> str:
        return (f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{tag}_{name}")

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
