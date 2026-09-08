"""One object that owns the message archive.

`main.py` creates a single `HistoryService`; the Bridge talks to it for every
read, the ActionEngine exposes it to the COLLECT_HISTORY block, and the
passive collector lives inside it. Keeping the wiring here means there is
exactly one database connection, one media cache and one parser in the
process, however many surfaces use them.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from typing import Optional

from backend.archive_lock import db_operation
from backend.db_paths import (PROTECTED_DATABASE, in_trash, protected_database,
                              same_database)
from backend.chat_parser import ChatParser, self_nick_history
from backend.collector import Collector, DEFAULTS as COLLECTOR_DEFAULTS
from backend.history_db import HistoryDB, inspect_archive
from backend.history_query import HistoryQuery
from backend.history_repo import HistoryRepo
from backend.media_store import MediaStore

log = logging.getLogger("chatbot")

#: The per-file cap before 2026-09-07 was 2 MB, which silently `skipped`
#: every ordinary chat GIF (2–15 MB) and is the root cause of Bug #2's
#: "received GIFs never save". The new default matches the in-page transfer
#: limit; stored configs carrying the old default are migrated up.
OLD_MAX_FILE_MB = 2
MAX_FILE_MB_DEFAULT = 25

HISTORY_DEFAULTS = {
    "enabled": True,
    "db_path": "history.db",
    "use_fts": True,
    "media": {
        "enabled": True,
        "download": True,
        "cache_dir": "saved_media",
        "max_file_mb": MAX_FILE_MB_DEFAULT,
        "max_cache_mb": 200,
    },
    "preview": {
        "preload_rows": 40,
        "page_size": 50,
        "max_rows": 400,
        "show_images": True,
    },
}


def _merge(base: dict, patch: dict) -> dict:
    """Deep-merge `patch` into a copy of `base`."""
    out = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class HistoryService:
    """Database + repository + query + media + parser + collector."""

    def __init__(self, cdp, config=None, db_path: Optional[str] = None,
                 session_id: str = "", memory=None):
        self.cdp = cdp
        self.config = config
        self.session_id = session_id or ""
        self.memory = memory
        self._settings = _merge(HISTORY_DEFAULTS, self._stored("history"))
        if db_path:
            self._settings["db_path"] = db_path
        self._migrate_media_cap()
        self.db = HistoryDB(self._settings["db_path"],
                            use_fts=bool(self._settings["use_fts"]))
        media_cfg = self._settings["media"]
        self.media = MediaStore(self.db, cdp=cdp,
                                cache_dir=media_cfg["cache_dir"],
                                max_file_mb=media_cfg["max_file_mb"],
                                max_cache_mb=media_cfg["max_cache_mb"],
                                enabled=bool(media_cfg["enabled"]))
        self.repo = HistoryRepo(self.db, media=self.media,
                                session_id=self.session_id)
        self.query = HistoryQuery(self.db)
        collector_cfg = _merge(COLLECTOR_DEFAULTS, self._stored("collector"))
        self.parser = ChatParser(
            cdp, chunk_size=int(collector_cfg.get("chunk_size", 80)),
            chunk_pause_ms=int(collector_cfg.get("chunk_pause_ms", 40)))
        self.collector = Collector(cdp=cdp, repo=self.repo, parser=self.parser,
                                   media=self.media, settings=collector_cfg,
                                   lease=getattr(cdp, "lease", None),
                                   memory=self.memory,
                                   identity_history=self.known_self_nicks)
        self._task: Optional[asyncio.Task] = None
        self._binding = False
        self.generation = 0

    # ── settings ─────────────────────────────────────────────────
    def _stored(self, section: str) -> dict:
        if self.config is None:
            return {}
        value = self.config.get(section, default={})
        return value if isinstance(value, dict) else {}

    def _migrate_media_cap(self) -> None:
        """Raise the per-file cap out of the 2 MB era (Bug #2, 2026-09-07).

        A cap of 2 MB made every ordinary chat GIF a permanent `skipped`
        row that no backfill could ever recover, so anything at or below
        the old default is bumped to the new 25 MB default. Deliberately
        larger configured values are kept.
        """
        media_cfg = self._settings.get("media") or {}
        try:
            cap = float(media_cfg.get("max_file_mb",
                                      MAX_FILE_MB_DEFAULT))
        except (TypeError, ValueError):
            cap = MAX_FILE_MB_DEFAULT
        if cap <= OLD_MAX_FILE_MB:
            media_cfg["max_file_mb"] = MAX_FILE_MB_DEFAULT
            self._settings["media"] = media_cfg

    @property
    def enabled(self) -> bool:
        return bool(self._settings.get("enabled", True))

    def known_self_nicks(self) -> list[str]:
        """Previously declared My Nick values survive Clear and DB switches."""
        history = self.config.get_state("my_nick_recent", []) if self.config else []
        return self_nick_history(history)

    @property
    def my_nick(self) -> str:
        return self.collector.my_nick

    def settings(self) -> dict:
        data = copy.deepcopy(self._settings)
        data["collector"] = self.collector.settings()
        data["fts"] = bool(self.db.fts_enabled)
        data["db_path"] = self.db.path
        return data

    def apply_settings(self, patch: dict) -> dict:
        """Merge a UI patch into the history settings and apply it live."""
        patch = dict(patch or {})
        # Changing a setting must not bypass validated Load.
        patch.pop("db_path", None)
        collector_patch = patch.pop("collector", None)
        self._settings = _merge(self._settings, patch)
        media_cfg = self._settings["media"]
        self.media.enabled = bool(media_cfg.get("enabled", True))
        self.media.cache_dir = media_cfg.get("cache_dir", self.media.cache_dir)
        self.media.max_file_bytes = int(float(
            media_cfg.get("max_file_mb", MAX_FILE_MB_DEFAULT)) * 1024 * 1024)
        self.media.max_cache_bytes = int(float(
            media_cfg.get("max_cache_mb", 200)) * 1024 * 1024)
        if collector_patch:
            self.collector.configure(**collector_patch)
        if self.config is not None:
            stored = {k: v for k, v in self._settings.items()
                      if k not in ("collector",)}
            self.config.set("history", stored)
            self.config.save()
        return self.settings()

    def set_my_nick(self, nick: str) -> str:
        clean = " ".join(str(nick or "").split()).strip()
        self.collector.configure(my_nick=clean)
        return clean

    # ── lifecycle ────────────────────────────────────────────────
    async def init(self) -> "HistoryService":
        await self._open_initial_db()
        folder = self._settings["media"].get("cache_dir")
        if folder:
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as e:
                log.warning("media cache folder unavailable: %s", e)
        try:
            # older builds wrote a flat <sha256>.<ext> pile — file it away
            moved = await self.media.migrate_layout()
            if moved:
                log.info("moved %d cached file(s) into the per-person "
                         "media tree", moved)
            # the page-only fetch could be blocked by CORS; give the rows that
            # failed before once more with the cookie-backed Python downloader
            retried = await self.media.retry_failed_uncached()
            if retried:
                log.info("re-queued %d media row(s) for the CORS-free "
                         "downloader", retried)
        except Exception as e:                        # noqa: BLE001
            log.warning("media layout migration skipped: %s", e)
        await self._install_push_binding()
        # A reconnect (or a Chrome restart) drops the binding — put it back.
        connected = getattr(self.cdp, "connected", None)
        if connected is not None and hasattr(connected, "connect"):
            connected.connect(lambda: asyncio.ensure_future(self._rebind()))
        disconnected = getattr(self.cdp, "disconnected", None)
        if disconnected is not None and hasattr(disconnected, "connect"):
            disconnected.connect(self._on_disconnected)
        log.info("Message archive ready: %s (fts=%s)", self.db.path,
                 self.db.fts_enabled)
        return self

    async def _open_initial_db(self) -> None:
        """Recover availability after an older build persisted a bad DB path.

        A broken original is NEVER overwritten or 'fixed' with empty columns.
        Prefer an existing valid archive. If none exists, create a separately
        named, validated archive so the application has a working writer.
        """
        requested = os.path.abspath(self.db.path)
        folder = os.path.dirname(requested)
        if in_trash(requested):
            folder = os.path.dirname(os.path.abspath(getattr(self.config, "_path", "config.json")))
        default = os.path.join(folder, "history.db")
        try:
            self._check_target(requested)
            if not os.path.exists(requested) and not same_database(requested, default) and inspect_archive(default):
                raise FileNotFoundError(f"configured archive is missing: {requested}")
            await self.db.init()
            return
        except Exception as exc:
            log.warning("Configured chat archive unavailable (%s): %s", requested,
                        getattr(exc, "detail", str(exc)))
        candidates = [default]
        if self.config is not None:
            recent = self.config.get_state("db_recent", [])
            if isinstance(recent, list):
                candidates += [p for p in recent if isinstance(p, str)]
        if os.path.isdir(folder):
            candidates += [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                           if n.lower().endswith(".db") and not n.startswith(".cvb-")]
        for path in candidates:
            fresh = None
            try:
                self._check_target(path)
                if same_database(path, requested) or not inspect_archive(path):
                    continue
                fresh = HistoryDB(path, use_fts=bool(self._settings.get("use_fts", True)))
                await fresh.init(allow_create=False)
                self._rebind_db(fresh)
                self._persist_db_path(path)
                log.warning("Recovered chat connection using %s; original file left untouched", path)
                return
            except Exception as exc:
                if fresh is not None:
                    await fresh.close()
                log.warning("Startup fallback refused %s: %s", path, getattr(exc, "detail", str(exc)))
        from backend.db_manager import DbManager
        manager = DbManager(config=self.config, service=self, root=folder)
        name = "history.db"
        number = 0
        while os.path.lexists(os.path.join(folder, name)) or self._protected_startup_name(os.path.join(folder, name)):
            number += 1
            name = f"history-recovery-{number}.db"
        made = await manager.create(os.path.join(folder, name))
        if not made.get("ok"):
            raise RuntimeError(made.get("error") or "Cannot initialize a working chat archive")
        await self.switch_db(made["path"])
        log.warning("Created recovery archive %s; existing files left untouched", made["path"])

    def _protected_startup_name(self, path: str) -> bool:
        return protected_database(path, memory=self.memory)

    async def _install_push_binding(self) -> None:
        """Let the in-page agent hand us new lines without polling."""
        if self._binding or not hasattr(self.cdp, "add_binding"):
            return
        try:
            ok = await self.cdp.add_binding("__cvbPush")
        except Exception as e:                        # noqa: BLE001
            log.debug("push binding unavailable: %s", e)
            return
        if not ok:
            return
        self._binding = True
        if hasattr(self.cdp, "on_event"):
            self.cdp.on_event("Runtime.bindingCalled", self._on_binding)

    async def _rebind(self) -> None:
        self._binding = False
        await self._install_push_binding()

    def _on_disconnected(self) -> None:
        self._binding = False

    def _on_binding(self, params: dict):
        if (params or {}).get("name") != "__cvbPush":
            return None
        return self.collector.handle_push((params or {}).get("payload") or "")

    def start(self) -> None:
        """Run the collector heartbeat in the background."""
        if self._task and not self._task.done():
            return
        if not self.enabled:
            return
        self._task = asyncio.ensure_future(self.collector.run())

    async def close(self) -> None:
        self.collector.stop()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):   # noqa: BLE001
                pass
            self._task = None
        async with self.db.operation_lock:
            await self.db.close()

    # ── swapping the database file (DB Connection window) ────────
    def _check_target(self, path: str) -> None:
        root = os.path.dirname(os.path.abspath(self.db.path))
        if protected_database(path, root=root, memory=self.memory) or in_trash(path):
            raise ValueError(PROTECTED_DATABASE)

    def _rebind_db(self, db: HistoryDB) -> None:
        """No await between assignments: every collaborator changes together."""
        db.operation_lock = self.db.operation_lock
        self.db = db
        self.repo.db = db
        self.query.db = db
        self.media.db = db
        self.generation += 1

    def _persist_db_path(self, path: str) -> None:
        self._settings["db_path"] = path
        if self.config is not None:
            stored = {k: v for k, v in self._settings.items() if k != "collector"}
            self.config.set("history", stored)
            self.config.save()

    async def switch_db(self, path: str) -> dict:
        """Validate the candidate while the original stays open and usable.

        The stable operation lock drains in-flight tick/push/manual reads and
        downloads. There is no stop/cancel/restart of collection and thus no
        loss of paused, running or throttled state. Failed opening never needs
        a dangerous 'reopen the old DB' recovery.
        """
        target = os.path.abspath(str(path or "").strip()) if path else ""
        if not target:
            raise ValueError("no database path given")
        self._check_target(target)
        lock = self.db.operation_lock
        if same_database(target, self.db.path) and self.db.is_open:
            async with lock:
                if same_database(target, self.db.path) and self.db.is_open:
                    await self.db.validate()
                    return self.settings()
        fresh = HistoryDB(target, use_fts=bool(self._settings.get("use_fts", True)))
        adopted = False
        try:
            await fresh.init(allow_create=False)
            async with lock:
                previous = self.db
                self._rebind_db(fresh)
                adopted = True
                self._persist_db_path(target)
                self.collector.reset_state()
                # A queued push belongs to the previous archive/gate and will
                # be refused until the next tick verifies the on-screen chat.
                try:
                    await previous.close()
                except Exception as exc:
                    # Adoption already succeeded. A cleanup error is not a
                    # failed Load and must not falsely report the old path.
                    log.warning("Archive switched; closing previous connection failed: %s", exc)
        finally:
            if not adopted:
                await fresh.close()
        log.info("Message archive switched to %s", target)
        return self.settings()

    # ── convenience used by the bridge ───────────────────────────
    @db_operation
    async def page(self, nick: str, **kwargs) -> dict:
        payload = await self.query.page(nick, **kwargs)
        payload["stats"] = await self.query.person_stats(nick)
        payload["my_nick"] = self.my_nick
        return payload

    def preview_settings(self) -> dict:
        return dict(self._settings.get("preview") or {})

    def to_json(self) -> str:
        return json.dumps(self.settings(), ensure_ascii=False)
