"""Cached media and the system clipboard.

`MediaMixin` answers where a media item lives, re-downloads one that
failed, opens the person's cache folder in the file manager, and puts a
media item or a selection of history text on the clipboard. A clipboard
that is not there (headless, no QApplication) is a reported `False`,
never an exception (RULE 4).
"""

from __future__ import annotations

import json
import logging
import os

from PySide6.QtCore import Slot

from core.events import LogMessage

from .support import _file_mime, _qt_clipboard

log = logging.getLogger("chatbot")


class MediaMixin:
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
            clipboard = _qt_clipboard()
            if clipboard is None:
                return False
            mode = payload.get("mode")
            path = payload.get("path") or ""
            if path and os.path.exists(path):
                # Carry the FILE itself, the path as text, and — for
                # still images — the pixels as well.
                clipboard.setMimeData(_file_mime(path, mode))
                return True
            if path:
                clipboard.setText(path)
                return True
            clipboard.setText(str(payload.get("text") or ""))
            return True
        except Exception as exc:                         # noqa: BLE001
            log.debug("clipboard unavailable: %s", exc)
            return False
