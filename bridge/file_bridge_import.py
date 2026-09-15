"""File bridge import slots — extracted from file_bridge (H-C5 split)

≤100 LOC.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Slot

from bridge.file_bridge_dialogs import _json, _library_of, pick_open_path
from bridge.file_bridge_orchestration import apply_block, apply_stack, import_file_result, merge_library, revalidate, save_imported_preset
from core.events import PresetsChanged

log = logging.getLogger("chatbot")


class FileBridgeImportMixin:
    @Slot(str, result=str)
    def import_file(self, kind: str) -> str:
        if kind not in ("stack", "block"):
            return self._err("unknown import kind")
        path = pick_open_path("Import a Chat-V-Bot preset file")
        if not path:
            self._log("⏹ Import cancelled", "warn")
            return _json({"ok": False, "canceled": True})
        return import_file_result(self, path, kind)

    @Slot(str, str, str, result=str)
    def apply_imported(self, preview_json: str, mode: str, stack_json: str) -> str:
        preview, fail = revalidate(self, preview_json)
        if fail:
            return fail
        if preview.kind == "block":
            return apply_block(self, preview, mode)
        if mode not in ("replace", "merge") or preview.kind != "stack":
            return self._err("bad import payload (stack + replace/merge)")
        current = self._clean(stack_json)
        stack = current + list(preview.stack) if mode == "merge" else list(preview.stack)
        added, replaced = merge_library(self, preview.custom_blocks)
        apply_stack(self, stack, current)
        saved_name = save_imported_preset(self, preview)
        payload = _json(_library_of(self.ctx.config))
        self.ctx.bus.emit(PresetsChanged(kind="custom_blocks", payload=payload))
        saved_note = f"; saved as preset “{saved_name}”" if saved_name else ""
        self._log(
            f"📥 Imported “{preview.name}” ({mode}) — "
            f"{len(stack)} block(s) in the stack, {added} added / "
            f"{replaced} replaced{saved_note} (↩ Undo)",
            "success",
        )
        return _json({"ok": True, "stack": stack, "blocks_added": added, "blocks_replaced": replaced, "preset_saved": saved_name or False})
