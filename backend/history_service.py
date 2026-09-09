"""One object that owns the message archive — and, since the unified
single-DB redesign, the WHOLE WORLD.

`main.py` creates a single `HistoryService`; the Bridge talks to it for
every read, the ActionEngine exposes it to the COLLECT_HISTORY block, and
the passive collector lives inside it. Keeping the wiring here means there
is exactly one database connection, one media cache and one parser in the
process, however many surfaces use them.

One DB = one complete world (docs/DB_CREATION_DELETION_REDESIGN_DESIGN_
2026-09-08.md): the database file carries the people queue (`users`), the
labels, the world-bound undo entries, the radar session state and the
per-world settings. `switch_db()` therefore tears the entire world down
and rebuilds it — queue connection included — so no state object can
outlive the switch, and a failed swap re-opens the previous file *and*
re-loads its world state before reporting the error (fail closed).
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

from backend.chat_parser import ChatParser
from backend.collector import Collector, DEFAULTS as COLLECTOR_DEFAULTS
from backend.history_db import HistoryDB
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

#: app_settings keys that make up the per-world half of the settings.
SETTING_KEYS = ("my_nick", "media_max_file_mb", "media_max_cache_mb",
                "preview")


def _merge(base: dict, patch: dict) -> dict:
    """Deep-merge `patch` into a copy of `base`."""
    out = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _db_stem(path: str) -> str:
    """`work.db` → `work` — the folder name of the world's media tree."""
    stem = os.path.splitext(os.path.basename(str(path or "")))[0]
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", stem).strip("._-")
    return stem or "world"


class HistoryService:
    """Database + repository + query + media + parser + collector."""

    def __init__(self, cdp, config=None, db_path: Optional[str] = None,
                 session_id: str = "", memory=None, labels=None):
        self.cdp = cdp
        self.config = config
        self.session_id = session_id or ""
        self.memory = memory            # the people queue — follows the world
        self._labels = labels           # the LabelStore — bound per world
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
                                   memory=self.memory)
        self._task: Optional[asyncio.Task] = None
        self._binding = False

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
        """Merge a UI patch into the history settings and apply it live.

        The media caps and preview are per-WORLD settings: the patch lands
        in config.json (the app-level template that seeds new worlds) AND
        in the active world's `app_settings` table.
        """
        patch = dict(patch or {})
        collector_patch = patch.pop("collector", None)
        self._settings = _merge(self._settings, patch)
        media_cfg = self._settings["media"]
        self.media.enabled = bool(media_cfg.get("enabled", True))
        self._apply_world_media_dir()
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
        self._persist_app_settings()
        return self.settings()

    def set_my_nick(self, nick: str) -> str:
        clean = " ".join(str(nick or "").split()).strip()
        self.collector.configure(my_nick=clean)
        self._persist_app_settings()
        return clean

    # ── per-world pieces ─────────────────────────────────────────
    def bind_labels(self, store) -> None:
        """Attach the bridge's LabelStore so switches reload it per world."""
        self._labels = store

    def media_base_dir(self) -> str:
        """The app-level media root (config value; default `saved_media`)."""
        media_cfg = self._settings.get("media") or {}
        return str(media_cfg.get("cache_dir") or "saved_media")

    def world_media_dir(self, path: str = "") -> str:
        """`<media root>/<world stem>` — one folder per database file."""
        return os.path.join(self.media_base_dir(), _db_stem(path or
                                                            self.db.path))

    def _apply_world_media_dir(self) -> None:
        """Point the media cache at the ACTIVE world's own folder."""
        if not self.db.is_open:
            self.media.cache_dir = self.media_base_dir()
            return
        self.media.cache_dir = self.world_media_dir()
        self.media._dirs.clear()          # nick→folder cache is world-bound

    def _persist_app_settings(self) -> None:
        """Write the per-world settings into the open database (best effort)."""
        if not self.db.is_open:
            return
        stamp = datetime.now().isoformat(timespec="seconds")
        rows = [
            ("my_nick", json.dumps(self.collector.my_nick or "")),
            ("media_max_file_mb", json.dumps(
                self._settings["media"].get("max_file_mb",
                                            MAX_FILE_MB_DEFAULT))),
            ("media_max_cache_mb", json.dumps(
                self._settings["media"].get("max_cache_mb", 200))),
            ("preview", json.dumps(self._settings.get("preview") or {})),
        ]
        async def work():
            try:
                for key, value in rows:
                    await self.db.execute(
                        "INSERT INTO app_settings(key, value, updated_at) "
                        "VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                        "value=excluded.value, updated_at=excluded.updated_at",
                        (key, value, stamp))
                await self.db.commit()
            except Exception as exc:        # noqa: BLE001
                log.debug("persist app settings failed: %s", exc)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return                          # nothing to schedule on
        loop.create_task(work())

    async def load_app_settings(self) -> None:
        """Apply the world's stored settings on top of the config template.

        Only keys that EXIST in the world override anything — a freshly
        created world therefore keeps the app template until the user edits
        something (and a new world is seeded explicitly by
        `seed_app_settings`).
        """
        rows = await self.db.fetchdicts("SELECT key, value FROM app_settings")
        data = {r["key"]: r["value"] for r in rows}
        media_cfg = dict(self._settings.get("media") or {})
        preview = dict(self._settings.get("preview") or {})
        try:
            if "my_nick" in data:
                nick = json.loads(str(data["my_nick"]))
                if isinstance(nick, str):
                    self.collector.configure(my_nick=nick)
            if "media_max_file_mb" in data:
                media_cfg["max_file_mb"] = float(data["media_max_file_mb"])
            if "media_max_cache_mb" in data:
                media_cfg["max_cache_mb"] = float(data["media_max_cache_mb"])
            if "preview" in data:
                stored = json.loads(str(data["preview"]))
                if isinstance(stored, dict):
                    preview = _merge(preview, stored)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            # a malformed per-world setting must never break a switch
            pass
        self._settings["media"] = media_cfg
        self._settings["preview"] = preview
        self.media.max_file_bytes = int(float(
            media_cfg.get("max_file_mb", MAX_FILE_MB_DEFAULT)) * 1024 * 1024)
        self.media.max_cache_bytes = int(float(
            media_cfg.get("max_cache_mb", 200)) * 1024 * 1024)

    async def seed_app_settings(self) -> None:
        """Give a FRESH world the app-template settings (D9 of the design).

        The seed comes from config.json — never from the previous world —
        so creation is not a data transfer. Only fills keys the world does
        not already have.
        """
        have = {r["key"] for r in await self.db.fetchdicts(
            "SELECT key FROM app_settings")}
        stamp = datetime.now().isoformat(timespec="seconds")
        media_cfg = self._settings.get("media") or {}
        rows = [
            ("my_nick", json.dumps(self.collector.my_nick or "")),
            ("media_max_file_mb", json.dumps(
                media_cfg.get("max_file_mb", MAX_FILE_MB_DEFAULT))),
            ("media_max_cache_mb", json.dumps(
                media_cfg.get("max_cache_mb", 200))),
            ("preview", json.dumps(self._settings.get("preview") or {})),
        ]
        for key, value in rows:
            if key in have:
                continue
            await self.db.execute(
                "INSERT INTO app_settings(key, value, updated_at) "
                "VALUES(?,?,?)", (key, value, stamp))
        await self.db.commit()

    # ── radar / observation state (gaze_data) ────────────────────
    async def load_gaze(self) -> None:
        """Restore this world's radar session state (partner + counters).

        The verified private-chat gate is deliberately NOT restored: RULE 15
        fails closed, so a fresh world re-verifies the conversation from
        scratch on its first tick.
        """
        try:
            rows = await self.db.fetchdicts("SELECT key, value FROM gaze_data")
        except Exception as exc:                      # noqa: BLE001
            log.debug("gaze load skipped: %s", exc)
            return
        data = {r["key"]: r["value"] for r in rows}
        if not data:
            return
        partner = str(data.get("partner") or "")
        if partner:
            self.collector._nick = partner
        for field in ("added", "total", "last_sync_added", "last_sync_count"):
            try:
                value = int(data.get(field))
            except (TypeError, ValueError):
                continue
            setattr(self.collector, "_" + field, value)
        for field in ("last_sync_reason",):
            if data.get(field):
                setattr(self.collector, "_" + field, str(data[field]))

    async def save_gaze(self) -> None:
        """Persist this world's radar state (called before close/switch)."""
        if not self.db.is_open:
            return
        nick = str(getattr(self.collector, "_nick", "") or "")
        if not nick:
            return
        stamp = datetime.now().isoformat(timespec="seconds")
        rows = [
            ("partner", nick),
            ("added", str(int(getattr(self.collector, "_added", 0) or 0))),
            ("total", str(int(getattr(self.collector, "_total", 0) or 0))),
            ("last_sync_reason",
             str(getattr(self.collector, "_last_sync_reason", "") or "")),
            ("last_sync_added",
             str(int(getattr(self.collector, "_last_sync_added", 0) or 0))),
            ("last_sync_count",
             str(int(getattr(self.collector, "_last_sync_count", 0) or 0))),
        ]
        try:
            for key, value in rows:
                await self.db.execute(
                    "INSERT INTO gaze_data(key, value, updated_at) "
                    "VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                    "value=excluded.value, updated_at=excluded.updated_at",
                    (key, value, stamp))
            await self.db.commit()
        except Exception as exc:                      # noqa: BLE001
            log.debug("gaze save failed: %s", exc)

    # ── lifecycle ────────────────────────────────────────────────
    async def init(self) -> "HistoryService":
        await self.db.init()
        await self.migrate_install()
        await self.load_app_settings()
        self._apply_world_media_dir()
        if self._labels is not None:
            try:
                await self._labels.load_from_db(self.db)
            except Exception as exc:                  # noqa: BLE001
                log.warning("label load from %s failed: %s",
                            self.db.path, exc)
        await self.load_gaze()
        folder = self.world_media_dir()
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
        log.info("Message archive ready: %s (fts=%s, world=%s)",
                 self.db.path, self.db.fts_enabled, self.world_media_dir())
        return self

    async def close(self) -> None:
        self.collector.stop()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):   # noqa: BLE001
                pass
            self._task = None
        try:
            await self.save_gaze()
            if self._labels is not None:
                await self._labels.flush_to_db()
        except Exception as exc:                       # noqa: BLE001
            log.warning("world flush on close failed: %s", exc)
        await self.db.close()

    # ── the in-page push channel (collector feed) ────────────────
    async def _install_push_binding(self) -> None:
        """Let the in-page agent hand us new lines without polling."""
        if self._binding or not hasattr(self.cdp, "add_binding"):
            return
        try:
            ok = await self.cdp.add_binding("__cvbPush")
        except Exception as e:                         # noqa: BLE001
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

    # ── one-time migration of a pre-unified install (D6) ─────────
    async def migrate_install(self) -> dict:
        """Re-home the parts of a legacy install that predate one-DB-worlds.

        Every step is idempotent (existence check or a schema_meta flag), so
        the hook is safe to run on every start — it only ever does work once
        per install. It re-homes data of the world that CURRENTLY owns the
        session; it never copies data between two world files (R6).
        """
        report = {"queue_merged": False, "labels_imported": False,
                  "recent_pruned": False, "undo_rehomed": False}
        if self.config is None:
            return report
        # 1 — the people queue lives in the world file now
        memory = self.memory
        if memory is not None:
            legacy = str(getattr(memory, "db_path", "") or "")
            if legacy and os.path.exists(legacy) and \
                    os.path.abspath(legacy) != os.path.abspath(self.db.path):
                try:
                    await self._merge_legacy_queue(legacy)
                    report["queue_merged"] = True
                except Exception as exc:               # noqa: BLE001
                    log.warning("queue merge from %s failed: %s", legacy, exc)
        # 2 — labels from the old global config section
        if self._labels is not None and \
                not await self.get_meta_flag("labels_migrated_from_config"):
            try:
                if await self._import_config_labels():
                    report["labels_imported"] = True
                    await self.set_meta_flag("labels_migrated_from_config")
            except Exception as exc:                   # noqa: BLE001
                log.warning("label import from config failed: %s", exc)
        # 3 — ghost paths in the remember list
        try:
            raw = self.config.get_state("db_recent", [])
            if isinstance(raw, list):
                kept = [p for p in raw if isinstance(p, str) and p and
                        os.path.exists(p)]
                if len(kept) != len(raw):
                    self.config.set_state(db_recent=kept[:12])
                    report["recent_pruned"] = True
        except Exception as exc:                       # noqa: BLE001
            log.debug("db_recent prune failed: %s", exc)
        # 4 — world-bound undo entries still living in config
        if not await self.get_meta_flag("undo_migrated_v6"):
            try:
                if await self._rehome_undo_entries():
                    report["undo_rehomed"] = True
                    await self.set_meta_flag("undo_migrated_v6")
            except Exception as exc:                   # noqa: BLE001
                log.warning("undo re-home failed: %s", exc)
        if any(report.values()):
            log.info("unified-DB migration: %s",
                     ", ".join(k for k, v in report.items() if v))
        return report

    async def get_meta_flag(self, key: str) -> bool:
        try:
            value = await self.db.get_meta(key, None)
            return value is not None and str(value) != ""
        except Exception:                              # noqa: BLE001
            return False

    async def set_meta_flag(self, key: str) -> None:
        try:
            await self.db.set_meta(key, "1")
            await self.db.commit()
        except Exception as exc:                       # noqa: BLE001
            log.warning("cannot set migration flag %s: %s", key, exc)

    async def _merge_legacy_queue(self, legacy_path: str) -> None:
        """chatbot.db → the world file, then the legacy file is renamed out.

        Rows that already exist by nick are kept, never overwritten (the
        world row wins). The legacy file is renamed, not deleted — user
        data is preserved, but it stops being a `.db` the DB window can see.
        """
        import aiosqlite
        async with aiosqlite.connect(legacy_path) as src:
            src.row_factory = aiosqlite.Row
            try:
                rows = await src.execute(
                    "SELECT nick, gender, registered, anonymous, guest, "
                    "first_seen, last_seen, messaged, message_count, "
                    "last_messaged, notes FROM users")
                legacy = [dict(r) for r in await rows.fetchall()]
            except Exception as exc:                   # noqa: BLE001
                raise RuntimeError(f"cannot read {legacy_path}: {exc}")
        inserted = 0
        for row in legacy:
            cur = await self.db.execute(
                "INSERT OR IGNORE INTO users(nick, gender, registered, "
                "anonymous, guest, first_seen, last_seen, messaged, "
                "message_count, last_messaged, notes) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (str(row.get("nick") or ""),
                 str(row.get("gender") or "unknown"),
                 int(row.get("registered") or 0),
                 int(row.get("anonymous") or 0),
                 int(row.get("guest") or 0),
                 row.get("first_seen") or "",
                 row.get("last_seen") or "",
                 int(row.get("messaged") or 0),
                 int(row.get("message_count") or 0),
                 row.get("last_messaged"),
                 str(row.get("notes") or "")))
            inserted += int(cur.rowcount or 0)
        await self.db.commit()
        # rename the legacy file (and any WAL siblings) out of the way
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            source = legacy_path + suffix
            if not os.path.exists(source):
                continue
            os.replace(source, legacy_path + f".migrated-{stamp}" + suffix)
        # the queue connection now follows the world
        if self.memory is not None:
            await self.memory.switch_db(self.db.path)
        log.info("merged %d/%d queue row(s) from %s into %s",
                 inserted, len(legacy), os.path.basename(legacy_path),
                 os.path.basename(self.db.path))

    async def _import_config_labels(self) -> bool:
        """config.json labels → this world's tables (once, only into an
        empty world)."""
        raw = self.config.get("labels", default=None)
        if not isinstance(raw, dict):
            return False
        defs = [d for d in (raw.get("defs") or []) if isinstance(d, dict)]
        assign = raw.get("assign") if isinstance(raw.get("assign"), dict) else {}
        if not defs and not assign:
            return False
        existing = int(await self.db.scalar("SELECT COUNT(*) FROM labels"))
        if existing:
            return False                     # world already has its own labels
        store = self._labels
        data = {
            "defs": defs,
            "assign": assign,
            "filter": raw.get("filter") or {"include": [], "exclude": []},
            "next_id": int(raw.get("next_id") or 0),
        }
        store._memory = copy.deepcopy(data)   # the DB is the store now
        store._dirty = True                   # …and it MUST reach the file
        await store.flush_to_db()
        return True

    async def _rehome_undo_entries(self) -> bool:
        """Move world-bound undo entries out of config.json into this world.

        Pre-unified installs keep the whole timeline in config. Every entry
        gets the monotonic `seq` it would have had in the unified model
        (list order = timeline order, so the interleaving is preserved),
        and the world-bound kinds are written into the world's
        `undo_history` table. config.json keeps only the app-level entries.
        """
        raw = self.config.get_state("undo_history", None)
        if not isinstance(raw, list) or not raw:
            return False
        entries = [e for e in raw if isinstance(e, dict)
                   and isinstance(e.get("kind"), str)]
        world_kinds = ("people", "labels", "archive", "dbconn")
        if not any(e.get("kind") in world_kinds for e in entries):
            return False
        # no seq yet → assign them in timeline order
        if all(not isinstance(e.get("seq"), int) for e in entries):
            for position, entry in enumerate(entries, start=1):
                entry["seq"] = position
            self.config.set_state(undo_history=copy.deepcopy(entries))
        moved = 0
        stamp = datetime.now().isoformat(timespec="seconds")
        for entry in entries:
            if entry.get("kind") not in world_kinds:
                continue
            seq = int(entry.get("seq") or 0)
            await self.db.execute(
                "INSERT OR IGNORE INTO undo_history(seq, kind, value, "
                "created_at) VALUES(?,?,?,?)",
                (seq, entry["kind"],
                 json.dumps(entry.get("value"), ensure_ascii=False), stamp))
            moved += 1
        await self.db.commit()
        if not moved:
            return False
        # config keeps only the app-level half (with its seq fields)
        app_entries = [e for e in entries if e.get("kind") not in world_kinds]
        self.config.set_state(undo_history=app_entries)
        return True

    # ── swapping the database file (DB Connection window) ────────
    async def _stop_collector(self) -> dict:
        """Park the collector so the file can be closed.

        Returns what was live, so the exact same state can be restored:
        the background loop AND the collector's own running flag (a tick
        driven by the app or a test does not need a task).
        """
        state = {
            "task": bool(self._task and not self._task.done()),
            "collector": bool(getattr(self.collector, "running", False)),
        }
        self.collector.stop()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):   # noqa: BLE001
                pass
            self._task = None
        return state

    def _restart_collector(self, state) -> None:
        """Put the collector back exactly as `_stop_collector` found it."""
        if not state:
            return
        if state.get("task"):
            self.start()                 # background loop + running flag
        elif state.get("collector"):
            self.collector.start()       # flag only: ticks stay manual

    def _rebind_db(self, db: HistoryDB) -> None:
        """Point every collaborator at the new connection (one DB per process)."""
        self.db = db
        self.repo.db = db
        self.query.db = db
        self.media.db = db

    async def _flush_labels(self) -> None:
        if self._labels is not None:
            try:
                await self._labels.flush_to_db()
            except Exception as exc:     # noqa: BLE001
                log.warning("label flush failed: %s", exc)

    async def _load_world_state(self) -> None:
        """Load everything world-bound out of the file now in `self.db`.

        Order matters: the volatile collector state is reset by the caller
        FIRST, then this restores the world's own settings, labels and radar
        state — a switched-into world shows exactly its own data and
        nothing from the world being left.
        """
        await self.load_app_settings()
        self._apply_world_media_dir()
        await self._flush_labels()       # no-op unless bound + dirty (old world)
        if self._labels is not None:
            try:
                await self._labels.load_from_db(self.db)
            except Exception as exc:     # noqa: BLE001
                log.warning("label load from %s failed: %s",
                            self.db.path, exc)
        await self.load_gaze()

    async def detach_db(self) -> bool:
        """Close the archive file without losing the service (used by delete)."""
        self._detached_running = await self._stop_collector()
        await self.db.close()
        return True

    async def switch_db(self, path: str) -> dict:
        """Open another database file — a FULL world restart.

        The collector is parked first and the current file closed (archive
        AND queue — the queue travels with its world), then the new file is
        opened and its world state loaded: per-world settings, labels, undo
        history (via the bridge) and radar state. The volatile collector
        state is reset in between, so nothing the old world learned about a
        conversation can leak into the new one.

        If the new file cannot be opened, the previous one is re-opened, the
        previous world's state is re-loaded and the collector put back — a
        failed swap must never leave the app without an archive, and never
        with a mix of two worlds.
        """
        target = str(path or "").strip()
        if not target:
            raise ValueError("no database path given")
        previous = self.db.path
        parked = getattr(self, "_detached_running", None)
        if parked is None:
            parked = await self._stop_collector()
        self._detached_running = None
        # persist the outgoing world's state BEFORE its file is closed
        try:
            await self.save_gaze()
        except Exception:                             # noqa: BLE001
            pass
        await self._flush_labels()
        if self.db.is_open:
            await self.db.close()
        fresh = HistoryDB(target, use_fts=bool(self._settings.get("use_fts", True)))
        try:
            # queue + archive open in ONE failure domain: either both point
            # at the new world or neither does
            if self.memory is not None:
                await self.memory.switch_db(target)
            await fresh.init()
        except Exception as exc:                          # noqa: BLE001
            log.warning("cannot open %s (%s) — reopening %s", target, exc,
                        previous)
            fallback = HistoryDB(
                previous, use_fts=bool(self._settings.get("use_fts", True)))
            try:
                await fallback.init()
                if self.memory is not None:
                    try:
                        await self.memory.switch_db(previous)
                    except Exception as inner:          # noqa: BLE001
                        log.warning("queue reopen on %s failed: %s",
                                    previous, inner)
                self._rebind_db(fallback)
                try:
                    await self._load_world_state()
                except Exception as inner:              # noqa: BLE001
                    log.warning("reloading previous world state failed: %s",
                                inner)
            except Exception as inner:                   # noqa: BLE001
                log.error("reopening %s failed too: %s", previous, inner)
            self._restart_collector(parked)
            raise
        self._rebind_db(fresh)
        self._settings["db_path"] = target
        if self.config is not None:
            stored = {k: v for k, v in self._settings.items()
                      if k not in ("collector",)}
            self.config.set("history", stored)
            self.config.save()
        # volatile state first (the new world starts cold — RULE 15),
        # then the new world's own persistent state
        try:
            self.collector.reset_state()
        except Exception:                                 # noqa: BLE001
            pass
        await self._load_world_state()
        self._restart_collector(parked)
        log.info("Message archive switched to %s (world restart complete)",
                 target)
        return self.settings()

    # ── world undo history (the world-bound half of the timeline) ─
    async def load_world_undo(self) -> list[dict]:
        """All world-bound undo entries of the open file, seq-ordered."""
        if not self.db.is_open:
            return []
        try:
            rows = await self.db.fetchall(
                "SELECT seq, kind, value FROM undo_history ORDER BY seq")
        except Exception as exc:                      # noqa: BLE001
            log.warning("undo load from %s failed: %s", self.db.path, exc)
            return []
        out = []
        for seq, kind, value in rows:
            try:
                out.append({"seq": int(seq), "kind": str(kind),
                            "value": json.loads(str(value))})
            except (TypeError, ValueError):
                continue
        return out

    async def save_world_undo(self, entries: list[dict]) -> None:
        """Rewrite the world's undo table to exactly `entries` (seq-ordered).

        The table is small (≤ the 100-entry timeline cap), so a delete-all +
        re-insert is the simplest correct sync and is transactional.
        """
        if not self.db.is_open:
            return
        try:
            await self.db.execute("DELETE FROM undo_history")
            for entry in entries or []:
                if not isinstance(entry, dict) or \
                        not isinstance(entry.get("seq"), int):
                    continue
                await self.db.execute(
                    "INSERT OR IGNORE INTO undo_history(seq, kind, value, "
                    "created_at) VALUES(?,?,?,?)",
                    (int(entry["seq"]), str(entry.get("kind") or ""),
                     json.dumps(entry.get("value"), ensure_ascii=False),
                     datetime.now().isoformat(timespec="seconds")))
            await self.db.execute(
                "DELETE FROM sqlite_sequence WHERE name='undo_history'")
            await self.db.commit()
        except Exception as exc:                      # noqa: BLE001
            log.warning("undo save to %s failed: %s", self.db.path, exc)

    # ── convenience used by the bridge ───────────────────────────
    async def page(self, nick: str, **kwargs) -> dict:
        payload = await self.query.page(nick, **kwargs)
        payload["stats"] = await self.query.person_stats(nick)
        payload["my_nick"] = self.my_nick
        return payload

    def preview_settings(self) -> dict:
        return dict(self._settings.get("preview") or {})

    def to_json(self) -> str:
        return json.dumps(self.settings(), ensure_ascii=False)
