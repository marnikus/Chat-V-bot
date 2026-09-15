"""FileBridge — facade (H-C5 split)

Now ≤60 LOC via export/import split.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, Signal

from bridge.file_bridge_dialogs import _json
from bridge.file_bridge_export import FileBridgeExportMixin
from bridge.file_bridge_import import FileBridgeImportMixin
from core.events import LogMessage
from services.run import normalize_blocks

log = logging.getLogger("chatbot")


class FileBridge(QObject, FileBridgeExportMixin, FileBridgeImportMixin):
    export_done = Signal(str)
    import_preview = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx

    def _log(self, message: str, level: str = "info") -> None:
        self.ctx.bus.emit(LogMessage(message=message, level=level))

    def _err(self, detail: str) -> str:
        self._log(f"❌ {detail}", "error")
        return _json({"ok": False, "error": detail})

    @staticmethod
    def _clean(stack_json: str) -> list[dict]:
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return []
        return normalize_blocks(blocks) if isinstance(blocks, list) else []
