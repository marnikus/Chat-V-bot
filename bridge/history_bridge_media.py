"""Media paths, the person media folder, and the clipboard.

Part of the `history_bridge` family (facade: `bridge/history_bridge.py`,
Round H step H-B1). `media_path` / `media_restore` answer over the
`media_ready` signal like every other read; `folder_for` and the folder
opening are synchronous; `copy_media` asks the archive for a clipboard
payload and hands it to the system clipboard — the helpers below carry the
FILE itself (as a URL and, for still images, the pixels as well) rather
than just a path string, so pasting into another app actually produces an
image.
"""

from __future__ import annotations

import json
import logging
import os

from core.events import LogMessage

log = logging.getLogger("chatbot")


async def media_path(bridge, req_id: str, media_ref: str) -> None:
    payload = await bridge.ctx.archive.media.path_for(media_ref)
    payload["req_id"] = req_id
    payload["id"] = media_ref
    bridge.media_ready.emit(req_id, json.dumps(payload, ensure_ascii=False))


async def media_restore(bridge, req_id: str, media_ref: str) -> None:
    payload = await bridge.ctx.archive.media.download_one(media_ref)
    payload["req_id"] = req_id
    payload["id"] = media_ref
    bridge.media_ready.emit(req_id, json.dumps(payload, ensure_ascii=False))


def folder_for(bridge, nick) -> str:
    """The media folder of a person, or "" when it cannot be determined."""
    if bridge.ctx.archive is None:
        return ""
    try:
        return bridge.ctx.archive.media.folder_for(str(nick or ""))
    except Exception as exc:                         # noqa: BLE001
        log.debug("media folder unavailable: %s", exc)
        return ""


def open_folder(bridge, folder: str) -> bool:
    """Open an existing media folder in the system file manager.

    The `os.makedirs` that prepares the folder is the facade's (the slot
    owns the synchronous side effect); this is the Qt half plus the
    announcements.
    """
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        ok = bool(QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
    except Exception as exc:                         # noqa: BLE001
        bridge.ctx.bus.emit(LogMessage(
            message=f"⚠ Cannot open {folder}: {exc}", level="warn"))
        return False
    bridge.ctx.bus.emit(LogMessage(message=f"📂 {folder}", level="info"))
    return ok


async def copy_media(bridge, media_ref: str) -> None:
    payload = await bridge.ctx.archive.media.clipboard_payload(media_ref)
    if payload.get("ok"):
        placed = to_clipboard(bridge, payload)
        payload["copied"] = placed
        if placed:
            bridge.ctx.bus.emit(LogMessage(
                message="📋 Copied " + (payload.get("path") or
                                        payload.get("text") or
                                        "media"), level="success"))
    bridge.media_ready.emit(str(media_ref),
                            json.dumps(payload, ensure_ascii=False))


def qt_clipboard():
    """The running Qt application's clipboard, or None when there is neither."""
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    if app is None:
        return None
    return app.clipboard()


def copy_file_to(clipboard, mode: str, path: str) -> bool:
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


def to_clipboard(bridge, payload: dict) -> bool:
    """Put text, a path or a whole file on the system clipboard."""
    try:
        clipboard = qt_clipboard()
        if clipboard is None:
            return False
        path = payload.get("path") or ""
        if path and os.path.exists(path):
            return copy_file_to(clipboard, payload.get("mode"), path)
        if path:
            clipboard.setText(path)
            return True
        clipboard.setText(str(payload.get("text") or ""))
        return True
    except Exception as exc:                         # noqa: BLE001
        log.debug("clipboard unavailable: %s", exc)
        return False
