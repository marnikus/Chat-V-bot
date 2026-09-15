"""WindowPresetBridge — facade (H-C5 split)

Now ≤100 LOC via export/crud split.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, Signal, Slot

from bridge.window_preset_crud import WindowPresetCrudMixin
from bridge.window_preset_export import _choose_export_folder, _open_in_folder, _write_export
from core.events import LogMessage
from services.window_preset_service import WindowPresetService

log = logging.getLogger("chatbot")


class WindowPresetBridge(QObject, WindowPresetCrudMixin):
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
        except Exception as exc:
            return None, f"load failed: {exc}"
        if document is None:
            return None, f"preset “{name}” was not found"
        clean, error = WindowPresetService.validate(document, name=name)
        return (None, error) if error else (clean, None)

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
        except Exception as exc:
            self._log(f"❌ Window preset export failed: {exc}", "error")
            return json.dumps({"ok": False, "error": str(exc)})
        self._exported_paths[document["name"]] = str(path)
        self._log(f"📤 Window preset exported to {path}", "success")
        return json.dumps({"ok": True, "name": document["name"], "path": str(path)}, ensure_ascii=False)

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
        except Exception as exc:
            self._log(f"❌ Cannot open preset folder: {exc}", "error")
            return False
        if opened:
            self._log(f"📂 Showing preset folder for {name}", "info")
        else:
            self._log(f"⚠ Cannot open preset folder for {name}", "warn")
        return opened
