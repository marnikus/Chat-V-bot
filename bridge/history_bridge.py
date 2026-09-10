"""HistoryBridge — the message archive: reads, deletions, media, clipboard.

Reads hit an async SQLite database, so a @Slot cannot answer inline: JS
passes a `req_id` and Python answers on a signal carrying the same id
(two windows can ask for two pages at once without answers crossing).
The archive service (services/history_service.py) owns the database.
"""

from __future__ import annotations

import json
import logging
import os

from PySide6.QtCore import QObject, Signal, Slot

from core.events import LogMessage, UserDbChanged

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

    # ── guarded async runner ─────────────────────────────────────
    def _run_async(self, scope: str, coro) -> None:
        async def guarded():
            try:
                await coro
            except Exception as exc:                     # noqa: BLE001
                log.warning("archive %s failed: %s", scope, exc)
                self.history_error.emit(scope, str(exc))
        self._schedule(guarded())

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

    def _need_archive(self, scope: str, req_id: str = "") -> bool:
        if self.ctx.archive is None:
            self.history_error.emit(scope, "the message archive is not "
                                            "running")
            return False
        return True

    # ── person history ───────────────────────────────────────────
    @Slot(str, str, str)
    def history_open(self, req_id, nick, options_json):
        if not self._need_archive("history_open", req_id):
            return
        opts = self._json_arg(options_json)
        self._run_async("history_open",
                        self._history_page(req_id, nick, opts))

    @Slot(str, str, str)
    def history_page(self, req_id, nick, anchor_json):
        if not self._need_archive("history_page", req_id):
            return
        opts = self._json_arg(anchor_json)
        self._run_async("history_page",
                        self._history_page(req_id, nick, opts))

    async def _history_page(self, req_id, nick, opts):
        service = self.ctx.archive
        limit = int(opts.get("limit") or
                    service.preview_settings().get("page_size", 50))
        if opts.get("around") is not None:
            payload = await service.query.around(
                nick, int(opts["around"]),
                radius=int(opts.get("radius") or 25))
            payload["stats"] = await service.query.person_stats(nick)
            payload["my_nick"] = service.my_nick
        else:
            payload = await service.page(
                nick,
                before_ord=(int(opts["before_ord"])
                            if opts.get("before_ord") is not None else None),
                after_ord=(int(opts["after_ord"])
                           if opts.get("after_ord") is not None else None),
                limit=limit)
        payload["req_id"] = req_id
        payload["preview"] = service.preview_settings()
        self.history_page_ready.emit(req_id, json.dumps(payload,
                                                        ensure_ascii=False))

    @Slot(str, str)
    def history_search(self, req_id, query_json):
        if not self._need_archive("history_search", req_id):
            return
        opts = self._json_arg(query_json)
        self._run_async("history_search", self._history_search(req_id, opts))

    async def _history_search(self, req_id, opts):
        service = self.ctx.archive
        query = str(opts.get("q") or opts.get("query") or "")
        limit = int(opts.get("limit") or 100)
        if str(opts.get("scope") or "person") == "person":
            payload = await service.query.search_person(
                str(opts.get("nick") or ""), query, limit=limit,
                offset=int(opts.get("offset") or 0))
            payload["scope"] = "person"
        else:
            payload = await service.query.search_global(query, limit=limit)
            payload["scope"] = "global"
        payload["req_id"] = req_id
        self.history_search_ready.emit(req_id, json.dumps(payload,
                                                          ensure_ascii=False))

    @Slot(str, str)
    def history_stats(self, req_id, nick):
        if not self._need_archive("history_stats", req_id):
            return

        async def work():
            payload = await self.ctx.archive.query.person_stats(nick)
            payload["req_id"] = req_id
            self.history_stats_ready.emit(req_id, json.dumps(
                payload, ensure_ascii=False))
        self._run_async("history_stats", work())

    # ── the all-time user database ───────────────────────────────
    @Slot(str, str)
    def userdb_page(self, req_id, query_json):
        if not self._need_archive("userdb_page", req_id):
            return
        opts = self._json_arg(query_json)

        async def work():
            payload = await self.ctx.archive.query.list_persons(
                q=str(opts.get("q") or ""),
                limit=int(opts.get("limit") or 50),
                offset=int(opts.get("offset") or 0),
                sort=str(opts.get("sort") or "recent"),
                # "" = the sort key's natural direction, so a payload written
                # before the sortable headers existed is unchanged
                dir=str(opts.get("dir") or ""),
                include_deleted=bool(opts.get("include_deleted")))
            payload["req_id"] = req_id
            payload["my_nick"] = self.ctx.archive.my_nick
            labels = self.ctx.people.labels_for_nicks(
                [item.get("nick") for item in payload.get("items") or []])
            for item in payload.get("items") or []:
                item["labels"] = labels.get(item.get("nick"), [])
            self.userdb_page_ready.emit(req_id, json.dumps(
                payload, ensure_ascii=False))
        self._run_async("userdb_page", work())

    @Slot(str)
    def userdb_stats(self, req_id):
        if not self._need_archive("userdb_stats", req_id):
            return

        async def work():
            payload = await self.ctx.archive.query.db_stats()
            payload["req_id"] = req_id
            payload.update(await self.ctx.archive.media.cache_usage())
            self.userdb_page_ready.emit(req_id, json.dumps(
                payload, ensure_ascii=False))
        self._run_async("userdb_stats", work())

    # ── deleting from the archive (all reversible, RULE 12) ──────
    @Slot(str, bool, result=bool)
    def history_delete_person(self, nick, hard=False):
        clean = " ".join(str(nick or "").split()).strip()
        if not clean:
            return False
        if self.ctx.archive is None:
            self.history_error.emit("history_delete_person",
                                    "the message archive is not running")
            return False

        async def work():
            archive = self.ctx.archive
            repo = archive.repo
            token = repo.new_op_token()
            people_before = await self._people_snapshot()
            ok = await repo.delete_person(clean, hard=bool(hard),
                                          token=token)
            if people_before is not None:
                try:
                    await self.ctx.memory.delete_user(clean)
                except Exception as exc:                  # noqa: BLE001
                    log.debug("people row for %s not removed: %s",
                              clean, exc)
            people_after = await self._people_snapshot()
            if ok and not hard:
                entry = {"op": "delete_person", "nick": clean,
                         "token": token}
                if people_before is not None and people_after is not None:
                    entry["people"] = {"before": people_before,
                                       "after": people_after}
                self.ctx.undo.push("archive", entry)
                self.ctx.bus.emit(LogMessage(
                    message=f"🗑 “{clean}” and their history removed — "
                            "Ctrl+Z restores both", level="warn"))
            elif ok and hard:
                self.ctx.label_store.forget(clean)
                self.ctx.bus.emit(LogMessage(
                    message=f"🔥 “{clean}” erased permanently "
                            "(not undoable)", level="warn"))
            self.userdb_changed.emit(json.dumps(
                {"action": "deleted", "nick": clean, "hard": bool(hard),
                 "ok": ok}, ensure_ascii=False))
            self._refresh_people()
        self._run_async("history_delete_person", work())
        return True

    @Slot(str, result=bool)
    def history_clear_person(self, nick):
        clean = " ".join(str(nick or "").split()).strip()
        if not clean:
            return False
        if self.ctx.archive is None:
            self.history_error.emit("history_clear_person",
                                    "the message archive is not running")
            return False

        async def work():
            archive = self.ctx.archive
            repo = archive.repo
            token = await repo.soft_delete_history(clean)
            if not token:
                if await repo.get_person(clean):
                    await repo.reset_cursor(clean)
                self.ctx.bus.emit(LogMessage(
                    message=f"ℹ “{clean}” has no messages to clear",
                    level="info"))
            else:
                self.ctx.undo.push("archive", {
                    "op": "clear_history", "nick": clean, "token": token})
                self.ctx.bus.emit(LogMessage(
                    message=f"🧹 History of “{clean}” cleared — the person "
                            "stays in the database and the chat is "
                            "re-collected from scratch (Ctrl+Z restores "
                            "the messages)", level="warn"))
            collector = getattr(archive, "collector", None)
            if collector is not None:
                try:
                    collector.person_cleared(clean)
                except Exception:                      # noqa: BLE001
                    pass
            self.userdb_changed.emit(json.dumps(
                {"action": "cleared", "nick": clean, "ok": bool(token)},
                ensure_ascii=False))
        self._run_async("history_clear_person", work())
        return True

    @Slot(str, str, result=bool)
    def history_delete_message(self, nick, message_id):
        clean = " ".join(str(nick or "").split()).strip()
        try:
            mid = int(str(message_id or "0").strip() or 0)
        except (TypeError, ValueError):
            mid = 0
        if not clean or mid <= 0:
            return False
        if self.ctx.archive is None:
            self.history_error.emit("history_delete_message",
                                    "the message archive is not running")
            return False

        async def work():
            token = await self.ctx.archive.repo.soft_delete_message(clean,
                                                                    mid)
            if not token:
                self.ctx.bus.emit(LogMessage(
                    message="⚠ That message is already gone", level="warn"))
                return
            self.ctx.undo.push("archive", {
                "op": "delete_message", "nick": clean, "token": token,
                "message_id": mid})
            self.ctx.bus.emit(LogMessage(
                message=f"🗑 One message removed from “{clean}” "
                        "(Ctrl+Z restores it)", level="info"))
            self.userdb_changed.emit(json.dumps(
                {"action": "message_deleted", "nick": clean, "id": mid},
                ensure_ascii=False))
        self._run_async("history_delete_message", work())
        return True

    @Slot(str, result=bool)
    def history_purge_deleted(self, nick):
        if self.ctx.archive is None:
            return False

        async def work():
            gone = await self.ctx.archive.repo.purge_deleted(
                " ".join(str(nick or "").split()).strip())
            self.ctx.bus.emit(LogMessage(
                message=f"🔥 {gone} hidden message(s) erased permanently",
                level="warn"))
            self.userdb_changed.emit(json.dumps(
                {"action": "purged", "nick": nick, "count": gone},
                ensure_ascii=False))
        self._run_async("history_purge_deleted", work())
        return True

    @Slot(str, result=bool)
    def history_restore_person(self, nick):
        if self.ctx.archive is None:
            return False

        async def work():
            ok = await self.ctx.archive.repo.restore_person(nick)
            self.userdb_changed.emit(json.dumps(
                {"action": "restored", "nick": nick, "ok": ok},
                ensure_ascii=False))
            self._refresh_people()
        self._run_async("history_restore_person", work())
        return True

    @Slot(str, str, result=bool)
    def history_merge(self, from_nick, into_nick):
        if self.ctx.archive is None:
            return False

        async def work():
            moved = await self.ctx.archive.repo.merge_persons(from_nick,
                                                              into_nick)
            self.userdb_changed.emit(json.dumps(
                {"action": "merged", "nick": into_nick, "from": from_nick,
                 "moved": moved}, ensure_ascii=False))
        self._run_async("history_merge", work())
        return True

    # ── helpers ──────────────────────────────────────────────────
    async def _people_snapshot(self):
        if self.ctx.memory is None:
            return None
        try:
            return await self.ctx.people.rows()
        except Exception as exc:                         # noqa: BLE001
            log.debug("people snapshot unavailable: %s", exc)
            return None

    def _refresh_people(self) -> None:
        from core.events import PeopleChanged
        self.ctx.bus.emit(PeopleChanged(reason="archive"))

    # ── media + clipboard ────────────────────────────────────────
    @Slot(str, str)
    def media_path(self, req_id, media_ref):
        if not self._need_archive("media_path", req_id):
            return

        async def work():
            payload = await self.ctx.archive.media.path_for(media_ref)
            payload["req_id"] = req_id
            payload["id"] = media_ref
            self.media_ready.emit(req_id, json.dumps(payload,
                                                     ensure_ascii=False))
        self._run_async("media_path", work())

    @Slot(str, str)
    def media_restore(self, req_id, media_ref):
        if not self._need_archive("media_restore", req_id):
            return

        async def work():
            payload = await self.ctx.archive.media.download_one(media_ref)
            payload["req_id"] = req_id
            payload["id"] = media_ref
            self.media_ready.emit(req_id, json.dumps(payload,
                                                     ensure_ascii=False))
        self._run_async("media_restore", work())

    @Slot(str, result=str)
    def media_folder(self, nick):
        if self.ctx.archive is None:
            return ""
        try:
            return self.ctx.archive.media.folder_for(str(nick or ""))
        except Exception as exc:                         # noqa: BLE001
            log.debug("media folder unavailable: %s", exc)
            return ""

    @Slot(str, result=bool)
    def open_media_folder(self, nick):
        folder = self.media_folder(nick)
        if not folder:
            return False
        try:
            os.makedirs(folder, exist_ok=True)
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            ok = bool(QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
        except Exception as exc:                         # noqa: BLE001
            self.ctx.bus.emit(LogMessage(
                message=f"⚠ Cannot open {folder}: {exc}", level="warn"))
            return False
        self.ctx.bus.emit(LogMessage(message=f"📂 {folder}", level="info"))
        return ok

    @Slot(str)
    def copy_media(self, media_ref):
        if self.ctx.archive is None:
            return

        async def work():
            payload = await self.ctx.archive.media.clipboard_payload(
                media_ref)
            if payload.get("ok"):
                placed = self._to_clipboard(payload)
                payload["copied"] = placed
                if placed:
                    self.ctx.bus.emit(LogMessage(
                        message="📋 Copied " + (payload.get("path") or
                                                payload.get("text") or
                                                "media"), level="success"))
            self.media_ready.emit(str(media_ref), json.dumps(
                payload, ensure_ascii=False))
        self._run_async("copy_media", work())

    @Slot(str, result=bool)
    def copy_text(self, text):
        """Copy selected history text through Qt (works without a browser)."""
        return self._to_clipboard({"mode": "text", "text": str(text or "")})

    @staticmethod
    def _to_clipboard(payload: dict) -> bool:
        try:
            from PySide6.QtGui import QGuiApplication, QImage
            app = QGuiApplication.instance()
            if app is None:
                return False
            clipboard = app.clipboard()
            if clipboard is None:
                return False
            mode = payload.get("mode")
            path = payload.get("path") or ""
            if path and os.path.exists(path):
                # Carry the FILE itself, the path as text, and — for
                # still images — the pixels as well.
                from PySide6.QtCore import QMimeData, QUrl
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(path)])
                mime.setText(path)
                if mode == "image":
                    image = QImage(path)
                    if not image.isNull():
                        mime.setImageData(image)
                clipboard.setMimeData(mime)
                return True
            if path:
                clipboard.setText(path)
                return True
            clipboard.setText(str(payload.get("text") or ""))
            return True
        except Exception as exc:                         # noqa: BLE001
            log.debug("clipboard unavailable: %s", exc)
            return False

    # ── archive settings ─────────────────────────────────────────
    @Slot(result=str)
    def get_history_settings(self):
        if self.ctx.archive is None:
            return json.dumps(self.ctx.config.get_copy("history",
                                                       default={}))
        return json.dumps(self.ctx.archive.settings(), ensure_ascii=False)

    @Slot(str)
    def save_history_settings(self, settings_json):
        patch = self._json_arg(settings_json)
        if self.ctx.archive is None:
            stored = self.ctx.config.get_copy("history", default={})
            stored.update(patch)
            self.ctx.config.set("history", stored)
            self.ctx.config.save()
            return
        self.ctx.archive.apply_settings(patch)
        self.ctx.bus.emit(LogMessage(message="💾 Archive settings saved",
                                     level="info"))

    # ── My Nick detection (reads the live page through the archive) ─
    @Slot(str)
    def detect_my_nick(self, req_id):
        if not self._need_archive("detect_my_nick", req_id):
            return

        async def work():
            state = await self.ctx.archive.parser.state()
            self.history_stats_ready.emit(req_id, json.dumps(
                {"req_id": req_id, "detected": state.get("me") or "",
                 "partner": state.get("partner") or ""},
                ensure_ascii=False))
        self._run_async("detect_my_nick", work())
