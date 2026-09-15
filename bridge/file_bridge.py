"""FileBridge — facade (H-C5 split)

Qt slots, now ≤200 LOC via dialogs/orchestration split.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from bridge.file_bridge_dialogs import _default_name, _json, _library_of, pick_open_path
from bridge.file_bridge_orchestration import (
    apply_block,
    apply_stack,
    export_file,
    import_file_result,
    merge_library,
    revalidate,
    save_imported_preset,
)
from core.events import LogMessage, PresetsChanged
from services.preset_io import build_block_export, build_stack_export
from services.run import normalize_blocks

log = logging.getLogger("chatbot")


class FileBridge(QObject):
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

    @Slot(str, result=str)
    def export_stack(self, stack_json: str) -> str:
        blocks = self._clean(stack_json)
        if not stack_json or not blocks:
            return self._err("the stack is empty or unreadable — " "nothing exported")
        saved = self.ctx.config.get_state("last_stack_preset", "") if self.ctx.config else None
        name = saved if isinstance(saved, str) and saved else "stack"
        payload = build_stack_export(name, blocks, _library_of(self.ctx.config))
        return export_file(
            self, payload, _default_name(name, name == "stack"), f"Exported “{name}” ({len(blocks)} blocks)"
        )

    @Slot(str, result=str)
    def export_stack_preset(self, name: str) -> str:
        presets = self.ctx.presets
        blocks = presets.load_stack(name) if presets else None
        if blocks is None:
            return self._err(f"preset “{name}” not found")
        blocks = normalize_blocks(blocks)
        payload = build_stack_export(name, blocks, _library_of(self.ctx.config))
        return export_file(
            self, payload, _default_name(name), f"Exported preset “{name}” " f"({len(blocks)} blocks)"
        )

    @Slot(str, result=str)
    def export_custom_block(self, name: str) -> str:
        name = (name or "").strip()
        entry = next(
            (e for e in _library_of(self.ctx.config) if isinstance(e, dict) and e.get("name") == name), None
        )
        if entry is None:
            return self._err(f"block preset “{name}” not found")
        try:
            payload = build_block_export(name, entry.get("block") or {})
        except ValueError as exc:
            return self._err(str(exc))
        return export_file(self, payload, _default_name(name), f"Exported block “{name}”")

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
        return _json(
            {
                "ok": True,
                "stack": stack,
                "blocks_added": added,
                "blocks_replaced": replaced,
                "preset_saved": saved_name or False,
            }
        )
