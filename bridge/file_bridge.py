"""FileBridge — portable export/import of stacks and custom blocks.

The ``FileBridge`` slots own exactly the Qt-shaped work: native file
dialogs and the signal/wire plumbing. The orchestration (merge into the
block library, apply to the engine, the validate-before-apply split)
lives on ``bridge.preset_applier.PresetApplier``, which Round I (I3)
extracted from the module-level functions that used to sit here — they
all took a ``bridge`` argument to reach nothing but ``ctx`` and ``_log``,
so that pair became the collaborator's state. All knowledge of the file
format lives in ``services.preset_io``; this module never parses the
payload itself twice: a preview is re-parsed from its RAW file text at
apply time.

Design: docs/STACK_PRESET_EXPORT_IMPORT_DESIGN_2026-09-10.md §4.2.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog

from bridge.preset_applier import PresetApplier
from core.events import LogMessage, PresetsChanged
from services.preset_io import build_block_export, build_stack_export
from services.run import normalize_blocks

log = logging.getLogger("chatbot")

FILE_FILTER = "Chat-V-Bot presets (*.json);;All files (*)"


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _slug(name: str) -> str:
    """A filesystem-safe default file name for a preset/block name."""
    bad = set('\\/:*?"<>|')
    cleaned = "".join("_" if c in bad else c for c in (name or "").strip())
    return cleaned or "stack"


def _default_name(name: str, timed: bool = False) -> str:
    """Default save name; the untimed current stack gets a timestamp so
    two exports can never silently clobber each other."""
    base = _slug(name)
    if not timed:
        return base + ".json"
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"{base}_{stamp}.json"


def _dialog_parent():
    app = QApplication.instance()
    return app.activeWindow() if app else None


def pick_save_path(caption: str, default_name: str) -> str:
    """Native save dialog; "" when the user cancels. Module-level on
    purpose so tests can monkeypatch it without a QApplication."""
    path, _ = QFileDialog.getSaveFileName(
        _dialog_parent(), caption, default_name, FILE_FILTER)
    return path or ""


def pick_open_path(caption: str) -> str:
    """Native open dialog; "" when the user cancels."""
    path, _ = QFileDialog.getOpenFileName(
        _dialog_parent(), caption, "", FILE_FILTER)
    return path or ""


class FileBridge(QObject):
    """Export/import slots; the router re-publishes them on the wire."""

    export_done = Signal(str)          # JSON: {ok, path} | {ok:false,…}
    import_preview = Signal(str)       # JSON preview, before anything applies

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.applier = PresetApplier(ctx, self._log)

    # ── shared helpers ───────────────────────────────────────────
    def _log(self, message: str, level: str = "info") -> None:
        self.ctx.bus.emit(LogMessage(message=message, level=level))

    def _err(self, detail: str) -> str:
        return self.applier.err(detail)

    def _export(self, payload: dict, default_name: str, done: str) -> str:
        """Save dialog (Qt) → applier writes it → emit on success."""
        path = pick_save_path("Export", default_name)
        result, announce = self.applier.export(path, payload, done)
        if announce is not None:
            self.export_done.emit(announce)
        return result

    @staticmethod
    def _clean(stack_json: str) -> list[dict]:
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return []
        return normalize_blocks(blocks) if isinstance(blocks, list) else []

    # ── export slots ─────────────────────────────────────────────
    @Slot(str, result=str)
    def export_stack(self, stack_json: str) -> str:
        blocks = self._clean(stack_json)
        if not stack_json or not blocks:
            return self._err("the stack is empty or unreadable — "
                             "nothing exported")
        saved = self.ctx.config.get_state("last_stack_preset", "") \
            if self.ctx.config else None
        name = saved if isinstance(saved, str) and saved else "stack"
        payload = build_stack_export(name, blocks, self.applier.library())
        return self._export(payload,
                            _default_name(name, name == "stack"),
                            f"Exported “{name}” ({len(blocks)} blocks)")

    @Slot(str, result=str)
    def export_stack_preset(self, name: str) -> str:
        presets = self.ctx.presets
        blocks = presets.load_stack(name) if presets else None
        if blocks is None:
            return self._err(f"preset “{name}” not found")
        blocks = normalize_blocks(blocks)
        payload = build_stack_export(name, blocks, self.applier.library())
        return self._export(payload, _default_name(name),
                            f"Exported preset “{name}” "
                            f"({len(blocks)} blocks)")

    @Slot(str, result=str)
    def export_custom_block(self, name: str) -> str:
        name = (name or "").strip()
        entry = next((e for e in self.applier.library()
                      if isinstance(e, dict) and e.get("name") == name),
                     None)
        if entry is None:
            return self._err(f"block preset “{name}” not found")
        try:
            payload = build_block_export(name, entry.get("block") or {})
        except ValueError as exc:
            return self._err(str(exc))
        return self._export(payload, _default_name(name),
                            f"Exported block “{name}”")

    # ── import slots ─────────────────────────────────────────────
    @Slot(str, result=str)
    def import_file(self, kind: str) -> str:
        if kind not in ("stack", "block"):
            return self._err("unknown import kind")
        path = pick_open_path("Import a Chat-V-Bot preset file")
        if not path:
            self._log("⏹ Import cancelled", "warn")
            return _json({"ok": False, "canceled": True})
        result, announce = self.applier.preview(path, kind)
        if announce is not None:
            self.import_preview.emit(announce)
        return result

    @Slot(str, str, str, result=str)
    def apply_imported(self, preview_json: str, mode: str,
                       stack_json: str) -> str:
        preview, fail = self.applier.revalidate(preview_json)
        if fail:
            return fail
        if preview.kind == "block":
            return self.applier.apply_block(preview, mode)
        if mode not in ("replace", "merge") or preview.kind != "stack":
            return self._err("bad import payload (stack + replace/merge)")
        current = self._clean(stack_json)
        stack = current + list(preview.stack) if mode == "merge" \
            else list(preview.stack)
        added, replaced = self.applier.merge_library(preview.custom_blocks)
        self.applier.apply_stack(stack, current)
        saved_name = self.applier.save_imported_preset(preview)
        payload = _json(self.applier.library())
        self.ctx.bus.emit(PresetsChanged(kind="custom_blocks",
                                         payload=payload))
        saved_note = f"; saved as preset “{saved_name}”" \
            if saved_name else ""
        self._log(f"📥 Imported “{preview.name}” ({mode}) — "
                  f"{len(stack)} block(s) in the stack, {added} added / "
                  f"{replaced} replaced{saved_note} (↩ Undo)", "success")
        return _json({"ok": True, "stack": stack,
                      "blocks_added": added,
                      "blocks_replaced": replaced,
                      "preset_saved": saved_name or False})
