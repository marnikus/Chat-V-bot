"""DbRegistry: internal operations on the DbManager facade state."""

from __future__ import annotations
import logging
import os
from .paths import TRASH_DIR, safe_db_name, db_stem, folder_size, file_group_size

log = logging.getLogger("chatbot")


class DbRegistry:
    def active_path(self) -> str:
        if self._service is not None:
            try:
                return self._service.db.path
            except Exception:  # noqa: BLE001
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
        return os.path.join(
            os.path.dirname(self.active_path()) or ".", safe_db_name(text)
        )

    def trash_dir(self) -> str:
        base = os.path.dirname(os.path.abspath(self.active_path())) or self.root
        return os.path.join(base, TRASH_DIR)

    def media_base_dir(self) -> str:
        """The app-level media root (one folder per world lives inside it)."""
        if self._service is not None:
            try:
                return self._service.media_base_dir()
            except Exception:  # noqa: BLE001
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
            items.append(
                {
                    "path": path,
                    "name": os.path.basename(path),
                    "bytes": file_group_size(path),
                    "exists": True,
                    "active": os.path.abspath(path) == os.path.abspath(active),
                    "can_delete": total >= 2,
                    "delete_hint": (
                        "Create a new database before deleting the last one"
                        if total < 2
                        else "Permanently delete this database and its media"
                    ),
                }
            )
        items.sort(key=lambda i: (not i["active"], i["name"].lower()))
        return items

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
            "persons": 0,
            "messages": 0,
            "messages_hidden": 0,
            "media": 0,
            "connected": False,
            "trash_dir": self.trash_dir(),
        }
        service = self._service
        if service is None or not getattr(service.db, "is_open", False):
            payload["total_bytes"] = payload["db_bytes"] + media_bytes
            return payload
        try:
            stats = await service.query.db_stats()
        except Exception as exc:  # noqa: BLE001
            log.warning("db stats failed: %s", exc)
            payload["error"] = str(exc)
            payload["total_bytes"] = payload["db_bytes"] + media_bytes
            return payload
        payload.update(
            {
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
            }
        )
        payload["total_bytes"] = payload["db_bytes"] + media_bytes
        return payload

    async def load(self, path: str, create: bool = False) -> dict:
        """Switch the running world over to another database file."""
        target = self.resolve(path)
        if not target:
            return {"ok": False, "error": "no database selected"}
        if not create and not os.path.exists(target):
            return {"ok": False, "error": f"{target} does not exist"}
        before = self.active_path()
        if os.path.abspath(target) == os.path.abspath(before) and not create:
            return {
                "ok": True,
                "op": "load",
                "path": target,
                "before_path": before,
                "unchanged": True,
            }
        if self._service is None:
            self._persist_path(target)
            self._remember(target)
            return {
                "ok": True,
                "op": "load",
                "path": target,
                "before_path": before,
                "offline": True,
            }
        try:
            await self._service.switch_db(target)
        except Exception as exc:  # noqa: BLE001
            log.warning("switching to %s failed: %s", target, exc)
            return {"ok": False, "error": str(exc), "path": target}
        self._persist_path(target)
        self._remember(target)
        return {"ok": True, "op": "load", "path": target, "before_path": before}

    def _forget(self, path: str) -> None:
        """Clean break: no reference to the deleted file survives."""
        self._prune_remembered()
        if self._config is None:
            return
        stored = self._config.get("history", "db_path", default="")
        if isinstance(stored, str) and os.path.abspath(stored) == os.path.abspath(path):
            replacement = self.active_path()
            if (
                replacement
                and os.path.exists(replacement)
                and os.path.abspath(replacement) != os.path.abspath(path)
            ):
                history = self._config.get("history", default={}) or {}
                if not isinstance(history, dict):
                    history = {}
                history = dict(history)
                history["db_path"] = replacement
                self._config.set("history", history)
                self._config.save()

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
            if os.path.abspath(item["path"]) != os.path.abspath(deleted) and item.get(
                "exists"
            ):
                return item["path"]
        return ""
