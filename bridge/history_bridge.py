"""HistoryBridge — the message archive: reads, deletions, media, clipboard.

Reads hit an async SQLite database, so a @Slot cannot answer inline: JS
passes a `req_id` and Python answers on a signal carrying the same id
(two windows can ask for two pages at once without answers crossing).
The archive service (services/history_service.py) owns the database.

Only the wire (Round H step H-B1): the seven Signals and the twenty-one
@Slots, every name and signature unchanged — the frontend calls them over
QWebChannel (tests/test_history_bridge.py pins them). The bodies live in
the four `history_bridge_*` part modules, which answer through the
bridge's signals.
"""

# ideal-size: the QWebChannel wire contract pins every @Slot signature the
# frontend expects; the slot bodies moved to the `history_bridge_*` parts in
# Round H step H-B1, so the ratchet (tools/metrics/rule16_gate.py) now guards
# the wire itself, where the gain lives. ROUND_F_DESIGN_2026-09-12.md §6, F4.
# The import block below is a clone-baseline pair with db_bridge.py — its
# first seven physical lines are pinned by tests/test_rule16_new_code.py;
# keep them verbatim.

from __future__ import annotations

import json
import logging
import os

from PySide6.QtCore import QObject, Signal, Slot

from core.events import LogMessage, UserDbChanged
from backend.history_query import (
    DEFAULT_LIMIT, DEFAULT_SORT, PersonPageRequest,
)
from services.world_events import run_when_world_open
from bridge import history_bridge_delete as delete
from bridge import history_bridge_media as media
from bridge import history_bridge_read as read
from bridge import history_bridge_settings as settings

log = logging.getLogger("chatbot")


def _person_request(opts: dict) -> PersonPageRequest:
    """The UI's JSON blob as a `PersonPageRequest`.

    Kept out of the `work()` closure so that closure stays a short, readable
    "fetch, decorate, emit" sequence.

    `dir` defaults to `""` — the sort key's *natural* direction — so a payload
    written before the sortable headers existed means exactly what it meant.
    """
    return PersonPageRequest(
        q=str(opts.get("q") or ""),
        limit=int(opts.get("limit") or DEFAULT_LIMIT),
        offset=int(opts.get("offset") or 0),
        sort=str(opts.get("sort") or DEFAULT_SORT),
        dir=str(opts.get("dir") or ""),
        include_deleted=bool(opts.get("include_deleted")))


class HistoryBridge(QObject):
    history_page_ready = Signal(str, str)    # req_id, JSON page
    history_search_ready = Signal(str, str)  # req_id, JSON results
    history_stats_ready = Signal(str, str)   # req_id, JSON stats
    userdb_page_ready = Signal(str, str)     # req_id, JSON persons / stats
    userdb_changed = Signal(str)             # JSON {action, nick}
    media_ready = Signal(str, str)           # req_id, JSON media info
    history_error = Signal(str, str)         # scope, message

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        ctx.bus.subscribe(UserDbChanged,
                          lambda e: self.userdb_changed.emit(e.payload))

    # ── guarded async runner ─────────────────────────────────────
    def _run_async(self, scope: str, coro) -> None:
        if not self._schedule(run_when_world_open(
                scope, coro, getattr(self.ctx.archive, "db", None),
                self.history_error.emit)):
            log.debug("no running event loop — %s dropped", scope)

    @staticmethod
    def _schedule(coro) -> bool:
        try:
            import asyncio
            asyncio.ensure_future(coro)
            return True
        except RuntimeError:
            coro.close()
            return False

    @staticmethod
    def _json_arg(raw, default=None):
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return dict(default or {})
        return data if isinstance(data, dict) else dict(default or {})

    def _ask(self, scope: str, fn, *args) -> bool:
        """Guard + schedule `fn(self, *args)`; False when the archive is
        missing (the caller is told, the slot still answers synchronously)."""
        if self.ctx.archive is None:
            self.history_error.emit(scope, "the message archive is not "
                                            "running")
            return False
        self._run_async(scope, fn(self, *args))
        return True

    def _run_if_archive(self, scope: str, fn, *args) -> bool:
        """Like `_ask` minus the error announcement — a silent refusal."""
        if self.ctx.archive is None:
            return False
        self._run_async(scope, fn(self, *args))
        return True

    # ── person history (bodies in history_bridge_read.py) ────────
    @Slot(str, str, str)
    def history_open(self, req_id, nick, options_json):
        self._ask("history_open", read.history_page, req_id, nick,
                  options_json)

    @Slot(str, str, str)
    def history_page(self, req_id, nick, anchor_json):
        self._ask("history_page", read.history_page, req_id, nick,
                  anchor_json)

    @Slot(str, str)
    def history_search(self, req_id, query_json):
        self._ask("history_search", read.history_search, req_id, query_json)

    @Slot(str, str)
    def history_stats(self, req_id, nick):
        self._ask("history_stats", read.history_stats, req_id, nick)

    # ── the all-time user database ───────────────────────────────
    @Slot(str, str)
    def userdb_page(self, req_id, query_json):
        self._ask("userdb_page", read.userdb_page, req_id,
                  _person_request(self._json_arg(query_json)))

    @Slot(str)
    def userdb_stats(self, req_id):
        self._ask("userdb_stats", read.userdb_stats, req_id)

    # ── deleting from the archive (all reversible, RULE 12) ──────
    @Slot(str, bool, result=bool)
    def history_delete_person(self, nick, hard=False):
        clean = " ".join(str(nick or "").split()).strip()
        if not clean:
            return False
        return self._ask("history_delete_person", delete.delete_person,
                         clean, bool(hard))

    @Slot(str, result=bool)
    def history_clear_person(self, nick):
        clean = " ".join(str(nick or "").split()).strip()
        if not clean:
            return False
        return self._ask("history_clear_person", delete.clear_person, clean)

    @Slot(str, str, result=bool)
    def history_delete_message(self, nick, message_id):
        clean = " ".join(str(nick or "").split()).strip()
        try:
            mid = int(str(message_id or "0").strip() or 0)
        except (TypeError, ValueError):
            mid = 0
        if not clean or mid <= 0:
            return False
        return self._ask("history_delete_message", delete.delete_message,
                         clean, mid)

    @Slot(str, result=bool)
    def history_purge_deleted(self, nick):
        return self._run_if_archive("history_purge_deleted",
                                    delete.purge_deleted, nick)

    @Slot(str, result=bool)
    def history_restore_person(self, nick):
        return self._run_if_archive("history_restore_person",
                                    delete.restore_person, nick)

    @Slot(str, str, result=bool)
    def history_merge(self, from_nick, into_nick):
        return self._run_if_archive("history_merge", delete.merge_persons,
                                    from_nick, into_nick)

    # ── media + clipboard (bodies in history_bridge_media.py) ────
    @Slot(str, str)
    def media_path(self, req_id, media_ref):
        self._ask("media_path", media.media_path, req_id, media_ref)

    @Slot(str, str)
    def media_restore(self, req_id, media_ref):
        self._ask("media_restore", media.media_restore, req_id, media_ref)

    @Slot(str, result=str)
    def media_folder(self, nick):
        return media.folder_for(self, nick)

    @Slot(str, result=bool)
    def open_media_folder(self, nick):
        folder = media.folder_for(self, nick)
        if not folder:
            return False
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception as exc:                         # noqa: BLE001
            self.ctx.bus.emit(LogMessage(
                message=f"⚠ Cannot open {folder}: {exc}", level="warn"))
            return False
        return media.open_folder(self, folder)

    @Slot(str)
    def copy_media(self, media_ref):
        self._run_if_archive("copy_media", media.copy_media, media_ref)

    @Slot(str, result=bool)
    def copy_text(self, text):
        """Copy selected history text through Qt (works without a browser)."""
        return media.to_clipboard(self, {"mode": "text",
                                         "text": str(text or "")})

    # ── archive settings (bodies in history_bridge_settings.py) ──
    @Slot(result=str)
    def get_history_settings(self):
        return settings.get_settings(self)

    @Slot(str)
    def save_history_settings(self, settings_json):
        settings.save_settings(self, self._json_arg(settings_json))

    # ── My Nick detection (reads the live page through the archive) ─
    @Slot(str)
    def detect_my_nick(self, req_id):
        self._ask("detect_my_nick", settings.detect_my_nick, req_id)
