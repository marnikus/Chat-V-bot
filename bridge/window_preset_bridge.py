"""WindowPresetBridge — persistent named grid-preset CRUD over QWebChannel."""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.events import LogMessage
from services.window_preset_service import WindowPresetService

log = logging.getLogger("chatbot")


class WindowPresetBridge(QObject):
    """Validate before atomic persistence and announce list changes live."""

    window_preset_list_updated = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx

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
        store = self._store()
        try:
            document = store.load_preset(name) if store else None
        except Exception as exc:  # noqa: BLE001
            self._log(f"❌ Window preset load failed: {exc}", "error")
            return "null"
        if document is None:
            self._log(f"❌ Window preset “{name}” not found", "error")
            return "null"
        clean, error = WindowPresetService.validate(document, name=name)
        if error:
            self._log(f"❌ Window preset “{name}” is invalid: {error}", "error")
            return "null"
        return json.dumps(clean, ensure_ascii=False)

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
