"""Window preset CRUD — extracted from window_preset_bridge (H-C5 split)

Save/load/delete/list, ≤150 LOC.
"""

from __future__ import annotations

import json
import logging

import os as _os

from PySide6.QtCore import Slot

from services.window_preset_service import WindowPresetService

log = logging.getLogger("chatbot")
_CRUD_VER = 1


class WindowPresetCrudMixin:
    @Slot(result=str)
    def list_window_presets(self):
        store = self._store()
        if store is None:
            return "[]"
        try:
            return self._emit_list(store)
        except Exception as exc:
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
        except Exception as exc:
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
        except Exception as exc:
            self._log(f"❌ Window preset deletion failed: {exc}", "error")
            return False
        self._emit_list(store)
        self._log(f"🗑 Window preset “{name}” deleted", "warn")
        return True
