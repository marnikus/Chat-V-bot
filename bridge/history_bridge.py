"""HistoryBridge — the message archive: reads, deletions, media, clipboard.

Reads hit an async SQLite database, so a @Slot cannot answer inline: JS
passes a `req_id` and Python answers on a signal carrying the same id
(two windows can ask for two pages at once without answers crossing).
The archive service (services/history_service.py) owns the database.

Only the wire (Round H step H-B1): the seven Signals and the twenty-one
@Slots, every name and signature unchanged — the frontend calls them over
QWebChannel (tests/test_history_bridge.py pins them). The bodies live in
the four `history_bridge_*` part modules, which answer through the
bridge's signals, plus `history_bridge_wire.py`, which owns the guard and
scheduling policy every slot shares.
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
from bridge import history_bridge_delete as delete
from bridge import history_bridge_media as media
from bridge import history_bridge_read as read
from bridge import history_bridge_settings as settings
from bridge import history_bridge_wire as wire

log = logging.getLogger("chatbot")


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

    # ── guarded async runner (policy in history_bridge_wire.py) ───
    def _run_async(self, scope: str, coro) -> None:
        """Schedule `coro` behind the world gate.

        Kept as a method because `bridge/router.py` schedules label-store
        work through it; the policy itself is `wire.run_async`.
        """
        wire.run_async(self, scope, coro)

    @staticmethod
    def _json_arg(raw, default=None):
        """The JS blob as a dict — the frontend may send nothing, a string
        or an object, and a hostile shape degrades to the caller's default
        rather than raising inside a Qt slot."""
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return dict(default or {})
        return data if isinstance(data, dict) else dict(default or {})

    # ── person history (bodies in history_bridge_read.py) ────────
    @Slot(str, str, str)
    def history_open(self, req_id, nick, options_json):
        wire.ask(self, "history_open", read.history_page, req_id, nick,
                  options_json)

    @Slot(str, str, str)
    def history_page(self, req_id, nick, anchor_json):
        wire.ask(self, "history_page", read.history_page, req_id, nick,
                  anchor_json)

    @Slot(str, str)
    def history_search(self, req_id, query_json):
        wire.ask(self, "history_search", read.history_search, req_id, query_json)

    @Slot(str, str)
    def history_stats(self, req_id, nick):
        wire.ask(self, "history_stats", read.history_stats, req_id, nick)

    # ── the all-time user database ───────────────────────────────
    @Slot(str, str)
    def userdb_page(self, req_id, query_json):
        wire.ask(self, "userdb_page", read.userdb_page, req_id,
                 self._json_arg(query_json))

    @Slot(str)
    def userdb_stats(self, req_id):
        wire.ask(self, "userdb_stats", read.userdb_stats, req_id)

    # ── deleting from the archive (all reversible, RULE 12) ──────
    @Slot(str, bool, result=bool)
    def history_delete_person(self, nick, hard=False):
        clean = " ".join(str(nick or "").split()).strip()
        if not clean:
            return False
        return wire.ask(self, "history_delete_person", delete.delete_person,
                         clean, bool(hard))

    @Slot(str, result=bool)
    def history_clear_person(self, nick):
        clean = " ".join(str(nick or "").split()).strip()
        if not clean:
            return False
        return wire.ask(self, "history_clear_person", delete.clear_person, clean)

    @Slot(str, str, result=bool)
    def history_delete_message(self, nick, message_id):
        clean = " ".join(str(nick or "").split()).strip()
        try:
            mid = int(str(message_id or "0").strip() or 0)
        except (TypeError, ValueError):
            mid = 0
        if not clean or mid <= 0:
            return False
        return wire.ask(self, "history_delete_message", delete.delete_message,
                         clean, mid)

    @Slot(str, result=bool)
    def history_purge_deleted(self, nick):
        return wire.run_if_archive(self, "history_purge_deleted",
                                    delete.purge_deleted, nick)

    @Slot(str, result=bool)
    def history_restore_person(self, nick):
        return wire.run_if_archive(self, "history_restore_person",
                                    delete.restore_person, nick)

    @Slot(str, str, result=bool)
    def history_merge(self, from_nick, into_nick):
        return wire.run_if_archive(self, "history_merge", delete.merge_persons,
                                    from_nick, into_nick)

    # ── media + clipboard (bodies in history_bridge_media.py) ────
    @Slot(str, str)
    def media_path(self, req_id, media_ref):
        wire.ask(self, "media_path", media.media_path, req_id, media_ref)

    @Slot(str, str)
    def media_restore(self, req_id, media_ref):
        wire.ask(self, "media_restore", media.media_restore, req_id, media_ref)

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
        wire.run_if_archive(self, "copy_media", media.copy_media, media_ref)

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
        wire.ask(self, "detect_my_nick", settings.detect_my_nick, req_id)
