"""HistoryBridge media + clipboard slots.

Split out of `bridge/history_bridge` in round H (H1). The slots stay on the
one QObject -- QWebChannel exposes a single object to JavaScript and every
`@Slot` name here is part of that wire contract -- so this is a MIXIN, not a
separate bridge. `HistoryBridge` inherits it and the frontend sees no change.

Why these seven and not others: they are the only slots that touch the media
cache and the desktop clipboard, and they share no state with the read or
delete slots beyond `self.ctx`. Cohesion, measured, is what chose the seam:
the class as a whole scores LCOM 0.31 and must not be scattered, but this
group is genuinely independent of the rest.

Imports point one way: `history_bridge` imports this; this imports only Qt,
`core` and the standard library.
"""

from __future__ import annotations

import json
import logging
import os

from PySide6.QtCore import Slot

from core.events import LogMessage

log = logging.getLogger("chatbot")


def _qt_clipboard():
    """The running Qt application's clipboard, or None when there is neither.

    Module-level because `HistoryBridge` is ratcheted at its frozen method
    count (tools/metrics/rule16_gate.py) and this needs nothing from it.
    """
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    if app is None:
        return None
    return app.clipboard()

def _copy_file_to(clipboard, mode: str, path: str) -> bool:
    """Carry the FILE itself, the path as text, and — for still images —
    the pixels as well."""
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QImage
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    mime.setText(path)
    if mode == "image":
        image = QImage(path)
        if not image.isNull():
            mime.setImageData(image)
    clipboard.setMimeData(mime)
    return True


class HistoryMediaMixin:
    """Media-cache reads and clipboard writes for the history window."""

    @Slot(str, str)
    def media_path(self, req_id, media_ref):
        if not self._need_archive("media_path", req_id):
            return

        async def work():
            payload = await self.ctx.archive.media.path_for(media_ref)
            self._reply(self.media_ready, req_id, payload, id=media_ref)
        self._run_async("media_path", work())
    @Slot(str, str)
    def media_restore(self, req_id, media_ref):
        if not self._need_archive("media_restore", req_id):
            return

        async def work():
            payload = await self.ctx.archive.media.download_one(media_ref)
            self._reply(self.media_ready, req_id, payload, id=media_ref)
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
        """Put text, a path or a whole file on the system clipboard."""
        try:
            clipboard = _qt_clipboard()
            if clipboard is None:
                return False
            path = payload.get("path") or ""
            if path and os.path.exists(path):
                return _copy_file_to(clipboard, payload.get("mode"), path)
            if path:
                clipboard.setText(path)
                return True
            clipboard.setText(str(payload.get("text") or ""))
            return True
        except Exception as exc:                         # noqa: BLE001
            log.debug("clipboard unavailable: %s", exc)
            return False
