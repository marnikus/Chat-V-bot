"""DbRegistry — the read half of `services.db_service.DbManager` (AREA C).

Owns every READ of the database registry: path resolution (with the
containment rule), the remembered-path list, the world scan, the DB-window
list and the size/count info payload. No mutation of databases happens
here; the write half lives in `services.db_lifecycle.DbLifecycle`.

The collaborator calls through its host (`host._config`, `host._service`,
`host.root`) so `DbManager` stays the only facade — every public name it
exposed before still works through a one-line delegate.
"""

from __future__ import annotations

import logging
import os

from services.db_service import (TRASH_DIR, SUFFIXES, db_stem,
                                 file_group_size, folder_size, safe_db_name)

log = logging.getLogger("chatbot")


def _stat_int(stats: dict, key: str) -> int:
    """One counter of a `db_stats()` payload, tolerating NULL/absent."""
    return int(stats.get(key) or 0)


def _apply_stats(payload: dict, stats: dict) -> None:
    """Fold a live `db_stats()` reading into the window payload.

    `db_bytes` keeps the on-disk measurement when the engine reports no
    size, so a connected world never shows 0 bytes.
    """
    payload.update({
        "connected": True,
        "db_bytes": int(stats.get("db_bytes") or payload["db_bytes"]),
        "text_bytes": _stat_int(stats, "text_bytes"),
        "persons": _stat_int(stats, "persons"),
        "persons_deleted": _stat_int(stats, "persons_deleted"),
        "messages": _stat_int(stats, "messages"),
        "messages_hidden": _stat_int(stats, "messages_hidden"),
        "media": _stat_int(stats, "media"),
        "media_cached": _stat_int(stats, "media_cached"),
        "fts": bool(stats.get("fts")),
    })


class DbRegistry:
    """Path resolution, remembered paths and world listing (reads only)."""

    def __init__(self, host):
        self._host = host

    # ── paths ────────────────────────────────────────────────────
    def active_path(self) -> str:
        host = self._host
        if host._service is not None:
            try:
                return host._service.db.path
            except Exception:                          # noqa: BLE001
                pass
        if host._config is not None:
            stored = host._config.get("history", "db_path",
                                      default="history.db")
            if isinstance(stored, str) and stored:
                return stored
        return "history.db"

    @staticmethod
    def _inside_root(candidate: str, root: str) -> bool:
        """True when `candidate` (absolute) is strictly inside `root`."""
        try:
            common = os.path.commonpath([root, candidate])
        except ValueError:                             # different drives
            return False
        return common == root and candidate != root

    def resolve(self, name_or_path: str) -> str:
        """Absolute-ish path for a user-supplied name (kept inside the app).

        Anything the user types must land INSIDE the app folder: absolute
        paths and separator-containing relatives are contained against
        `host.root`, and names that would escape resolve to "" (the
        create/load/delete gates refuse loudly).
        """
        text = str(name_or_path or "").strip()
        if not text:
            return ""
        root = os.path.abspath(self._host.root)
        if os.path.isabs(text):
            candidate = os.path.abspath(os.path.normpath(text))
        elif os.sep in text or "/" in text:
            base = os.path.dirname(os.path.abspath(self.active_path()))
            candidate = os.path.abspath(os.path.join(base,
                                                     os.path.normpath(text)))
        else:
            return os.path.join(
                os.path.dirname(os.path.abspath(self.active_path())),
                safe_db_name(text))
        if not self._inside_root(candidate, root):
            return ""
        return candidate

    def trash_dir(self) -> str:
        base = os.path.dirname(os.path.abspath(self.active_path())) \
            or self._host.root
        return os.path.join(base, TRASH_DIR)

    def media_base_dir(self) -> str:
        """The app-level media root (one folder per world lives inside it)."""
        host = self._host
        if host._service is not None:
            try:
                return host._service.media_base_dir()
            except Exception:                          # noqa: BLE001
                pass
        if host._config is not None:
            media = host._config.get("history", "media", default={}) or {}
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
        host = self._host
        if host._config is not None:
            raw = host._config.get_state("db_recent", [])
            if isinstance(raw, list):
                stored = [p for p in raw if isinstance(p, str) and p]
        return stored

    def _remember(self, path: str) -> None:
        host = self._host
        if host._config is None or not path:
            return
        recent = [p for p in self.known_paths() if p != path]
        recent.insert(0, path)
        host._config.set_state(db_recent=recent[:12])

    def _prune_remembered(self) -> None:
        """Drop remembered paths whose file is gone (the "missing" ghosts).

        `db_recent` is a recall list, not a registry: a file that does not
        exist on disk must never reach the UI (D3 of the design).
        """
        host = self._host
        if host._config is None:
            return
        stored = self.known_paths()
        kept = [p for p in stored if os.path.exists(p)]
        if len(kept) != len(stored):
            host._config.set_state(db_recent=kept[:12])

    def deletion_inventory_sources(self, victim_abs: str = "") -> dict:
        """Raw source lists for the AREA A deletion inventory (read-only).

        Returns {"active_folder": [...], "victim_folder": [...],
        "remembered": [...], "active": ...}. Existing methods are unchanged;
        `services.db_deletion.build_deletion_inventory` combines these with
        dedup + completeness tracking. Worlds outside these sources are NOT
        scanned (see SUPPORTED_BOUNDARY).
        """
        try:
            active_folder = list(self.existing_worlds() or [])
        except Exception:  # noqa: BLE001
            active_folder = []
        victim_folder = _victim_folder_db_files(self, victim_abs)
        remembered = _remembered_existing_dbs(self)
        try:
            active = self.active_path()
        except Exception:  # noqa: BLE001
            active = ""
        return {"active_folder": active_folder,
                "victim_folder": victim_folder,
                "remembered": remembered, "active": active}

    def existing_worlds(self) -> list[str]:
        """Every database file that EXISTS: the folder scan + the active file."""
        active = self.active_path()
        folder = os.path.dirname(os.path.abspath(active)) or self._host.root
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
        service = self._host._service
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
        _apply_stats(payload, stats)
        payload["total_bytes"] = payload["db_bytes"] + media_bytes
        return payload


# ── raw source helpers for the deletion inventory ──────────────────

def _victim_folder_db_files(registry, victim_abs: str) -> list:
    """Existing `*.db` files in the victim directory (raw source list).

    The directory is skipped when it is the active world's directory.
    Best-effort like the old inline form: any OSError yields no files.
    """
    from services import db_deletion
    if not victim_abs:
        return []
    victim_dir = os.path.dirname(
        os.path.abspath(str(victim_abs))) or ""
    try:
        active = registry.active_path()
        active_dir = os.path.dirname(
            os.path.abspath(active)) if active else ""
    except Exception:  # noqa: BLE001
        active_dir = ""
    files: list[str] = []
    if victim_dir and os.path.isdir(victim_dir) and \
            os.path.abspath(victim_dir) != os.path.abspath(
                active_dir or victim_dir + "_x"):
        # Listing failures were swallowed in the inline original too;
        # _append_db_files only reports them for the managed inventory.
        try:
            db_deletion._append_db_files(files, victim_dir)
        except OSError:
            return []
    return files


def _remembered_existing_dbs(registry) -> list:
    """Remembered `*.db` paths that still exist (raw source list)."""
    try:
        return [p for p in (registry.known_paths() or [])
                if isinstance(p, str) and p.lower().endswith(".db")
                and os.path.exists(p)]
    except Exception:  # noqa: BLE001
        return []
