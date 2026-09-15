"""File bridge export slots — extracted from file_bridge (H-C5 split)

≤100 LOC.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Slot

from bridge.file_bridge_dialogs import _default_name, _json, _library_of
from bridge.file_bridge_orchestration import export_file
from services.preset_io import build_block_export, build_stack_export
from services.run import normalize_blocks

log = logging.getLogger("chatbot")


class FileBridgeExportMixin:
    @Slot(str, result=str)
    def export_stack(self, stack_json: str) -> str:
        blocks = self._clean(stack_json)
        if not stack_json or not blocks:
            return self._err("the stack is empty or unreadable — " "nothing exported")
        saved = self.ctx.config.get_state("last_stack_preset", "") if self.ctx.config else None
        name = saved if isinstance(saved, str) and saved else "stack"
        payload = build_stack_export(name, blocks, _library_of(self.ctx.config))
        return export_file(self, payload, _default_name(name, name == "stack"), f"Exported “{name}” ({len(blocks)} blocks)")

    @Slot(str, result=str)
    def export_stack_preset(self, name: str) -> str:
        presets = self.ctx.presets
        blocks = presets.load_stack(name) if presets else None
        if blocks is None:
            return self._err(f"preset “{name}” not found")
        blocks = normalize_blocks(blocks)
        payload = build_stack_export(name, blocks, _library_of(self.ctx.config))
        return export_file(self, payload, _default_name(name), f"Exported preset “{name}” " f"({len(blocks)} blocks)")

    @Slot(str, result=str)
    def export_custom_block(self, name: str) -> str:
        name = (name or "").strip()
        entry = next((e for e in _library_of(self.ctx.config) if isinstance(e, dict) and e.get("name") == name), None)
        if entry is None:
            return self._err(f"block preset “{name}” not found")
        try:
            payload = build_block_export(name, entry.get("block") or {})
        except ValueError as exc:
            return self._err(str(exc))
        return export_file(self, payload, _default_name(name), f"Exported block “{name}”")
