"""WindowPresetBridge — persistent named grid-preset CRUD over QWebChannel."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from core.events import LogMessage
from services.window_preset_service import WindowPresetService

log = logging.getLogger("chatbot")


def _safe_filename(name: str) -> str:
    stem = re.sub(r"[^\w-]+", "-", str(name), flags=re.UNICODE).strip("-_")
    return f"window-preset-{stem or 'untitled'}.json"


def _choose_export_folder() -> str:
    from PySide6.QtWidgets import QFileDialog

    return str(QFileDialog.getExistingDirectory(
        None, "Export window preset — choose a folder", str(Path.home())))


def _write_export(folder: str, document: dict) -> Path:
    target = Path(folder) / _safe_filename(document["name"])
    temporary = target.with_name(f".{target.name}.tmp")
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def _open_in_folder(path: str) -> bool:
    target = Path(path)
    folder = target if target.is_dir() else target.parent
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))


class WindowPresetBridge(QObject):
    """Validate before atomic persistence and announce list changes live."""

    window_preset_list_updated = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._exported_paths = {}

    def _store(self):
        config = self.ctx.config
        return getattr(config, "window_presets", None) if config else None

    def _log(self, message: str, level: str = "info") -> None:
        self.ctx.bus.emit(LogMessage(message=message, level=level))

    def _emit_list(self, store) -> str:
        payload = json.dumps(store.list_presets(), ensure_ascii=False)
        self.window_preset_list_updated.emit(payload)
        return payload

    def _flush(self, store) -> bool:
        if store.save(force=True):
            return True
        store.load()
        return False

    def _validated_document(self, name):
        store = self._store()
        if store is None:
            return None, "window presets are unavailable"
        try:
            document = store.load_preset(name)
        except Exception as exc:  # noqa: BLE001
            return None, f"load failed: {exc}"
        if document is None:
            return None, f"preset “{name}” was not found"
        clean, error = WindowPresetService.validate(document, name=name)
        return (None, error) if error else (clean, None)

    @Slot(result=str)
    def list_window_presets(self):
        store = self._store()
        if store is None:
            return "[]"
        try:
            return self._emit_list(store)
        except Exception as exc:  # noqa: BLE001
            log.error("window preset list failed: %s", exc)
            return "[]"

    @Slot(str, str, result=bool)
    def save_window_preset(self, name, payload):
        document, error = WindowPresetService.validate(payload, name=name)
        if error:
            self._log(f"❌ Window preset save rejected: {error}", "error")
            return False
        store = self._store()
        if store is None:
            self._log("❌ Window presets are unavailable", "error")
            return False
        try:
            store.save_preset(document["name"], document)
            if not self._flush(store):
                self._log("❌ Window preset could not be written to disk", "error")
                return False
        except Exception as exc:  # noqa: BLE001
            self._log(f"❌ Window preset save failed: {exc}", "error")
            return False
        self._emit_list(store)
        self._log(f"💾 Window preset “{document['name']}” saved", "success")
        return True

    @Slot(str, result=str)
    def load_window_preset(self, name):
        document, error = self._validated_document(name)
        if error:
            self._log(f"❌ Window preset “{name}”: {error}", "error")
            return "null"
        return json.dumps(document, ensure_ascii=False)

    @Slot(str, result=str)
    def export_window_preset(self, name):
        document, error = self._validated_document(name)
        if error:
            self._log(f"❌ Window preset export refused: {error}", "error")
            return json.dumps({"ok": False, "error": error})
        try:
            folder = _choose_export_folder()
            if not folder:
                self._log("Window preset export cancelled", "info")
                return json.dumps({"ok": False, "cancelled": True})
            path = _write_export(folder, document)
        except Exception as exc:  # noqa: BLE001
            self._log(f"❌ Window preset export failed: {exc}", "error")
            return json.dumps({"ok": False, "error": str(exc)})
        self._exported_paths[document["name"]] = str(path)
        self._log(f"📤 Window preset exported to {path}", "success")
        return json.dumps({"ok": True, "name": document["name"],
                           "path": str(path)}, ensure_ascii=False)

    @Slot(str, result=bool)
    def show_window_preset_in_folder(self, name):
        store = self._store()
        path = self._exported_paths.get(str(name))
        if not path and store is not None:
            path = getattr(store, "path", "")
        if not path:
            self._log("⚠ Window preset folder is unavailable", "warn")
            return False
        try:
            opened = _open_in_folder(path)
        except Exception as exc:  # noqa: BLE001
            self._log(f"❌ Cannot open preset folder: {exc}", "error")
            return False
        if opened:
            self._log(f"📂 Showing preset folder for {name}", "info")
        else:
            self._log(f"⚠ Cannot open preset folder for {name}", "warn")
        return opened

    @Slot(str, result=bool)
    def delete_window_preset(self, name):
        store = self._store()
        try:
            if store is None or not store.delete_preset(name):
                self._log(f"⚠ Window preset “{name}” not found", "warn")
                return False
            if not self._flush(store):
                self._log("❌ Window preset deletion could not be written", "error")
                return False
        except Exception as exc:  # noqa: BLE001
            self._log(f"❌ Window preset deletion failed: {exc}", "error")
            return False
        self._emit_list(store)
        self._log(f"🗑 Window preset “{name}” deleted", "warn")
        return True
