"""FileBridge — portable export/import of stacks and custom blocks.

The ``FileBridge`` slots own exactly the Qt-shaped work: native file
dialogs and the signal/wire plumbing. The orchestration (merge into the
block library, apply to the engine, the validate-before-apply split)
lives in the module-level functions below so it is testable without a
QObject instance, and all knowledge of the file format lives in
``services.preset_io`` — this module never parses the payload itself
twice: a preview is re-parsed from its RAW file text at apply time.

Design: docs/STACK_PRESET_EXPORT_IMPORT_DESIGN_2026-09-10.md §4.2.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog

from core.events import LogMessage, PresetsChanged, StackLoaded
from services.preset_io import (PresetPreview, build_block_export,
                                build_stack_export, parse_export,
                                preview_dict, read_export_file,
                                write_export)
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


def _library_of(config: Any) -> list[dict]:
    return config.blocks.all() if config is not None else []


# ── orchestration (no QObject needed; `bridge` is only its ctx/_log) ─

def merge_library(bridge: "FileBridge", entries) -> "tuple[int, int]":
    """Merge imported custom blocks into the block library. Same name =
    same block: a collision overwrites, and both outcomes are counted
    for the log line."""
    if not entries or bridge.ctx.config is None:
        return 0, 0
    store = bridge.ctx.config.blocks
    items = store.all()
    added = replaced = 0
    for entry in entries:
        name = entry.get("name", "")
        existed = any(b.get("name") == name for b in items)
        # entries come from a re-validated preview: `block` is a dict
        result = store.save_custom_block(name, entry["block"])
        if result.is_err:
            bridge._log(f"⚠ Block “{name}” not saved: "
                        f"{result.err().detail}", "warn")
            continue
        if existed:
            replaced += 1
        else:
            added += 1
    if added or replaced:
        bridge.ctx.config.save()
    return added, replaced


def apply_stack(bridge: "FileBridge", stack: list[dict],
                current: list[dict]) -> None:
    """Load the new stack into the engine and persist it. The pre-import
    stack is pushed to the ONE global undo history (RULE 12)."""
    if current and current != stack:
        bridge.ctx.undo.push_stack(current)
    engine = bridge.ctx.engine
    if engine is not None:
        engine.load_stack(list(stack))
    if bridge.ctx.config is not None:
        bridge.ctx.config.set_state(last_stack=list(stack),
                                    last_stack_preset="")
    bridge.ctx.bus.emit(StackLoaded(name="import", payload=_json(stack)))


def apply_block(bridge: "FileBridge", preview: PresetPreview,
                mode: str) -> str:
    """Add one imported block to the library (mode "add" only)."""
    if mode != "add" or not isinstance(preview.block, dict):
        return bridge._err("a block file needs mode “add” with a block")
    if bridge.ctx.config is None:
        return bridge._err("no block library available")
    saved = bridge.ctx.config.blocks.save_custom_block(preview.name,
                                                       preview.block)
    if saved.is_err:
        return bridge._err("block library rejected the import: "
                           f"{saved.err().detail}")
    bridge.ctx.config.save()
    payload = _json(bridge.ctx.config.blocks.all())
    bridge.ctx.bus.emit(PresetsChanged(kind="custom_blocks", payload=payload))
    bridge._log(f"📥 Block “{preview.name}” added to the library",
                "success")
    return _json({"ok": True, "name": preview.name})


def save_imported_preset(bridge: "FileBridge", preview: PresetPreview):
    """The imported file is also a named preset: register it in the
    saved-preset list so it shows up in Select Preset right away
    (same name = same preset: a re-import refreshes it)."""
    presets = bridge.ctx.presets
    if presets is None or not preview.stack:
        return False
    try:
        presets.save_stack(preview.name, list(preview.stack))
        saved = presets.save(force=True)
    except (ValueError, OSError) as exc:
        bridge._log(f"⚠ Imported preset not saved: {exc}", "warn")
        return False
    if not saved:
        bridge._log("⚠ Imported preset could not be persisted to disk",
                    "warn")
        return False
    payload = _json(presets.list_stacks())
    bridge.ctx.bus.emit(PresetsChanged(kind="stacks", payload=payload))
    return preview.name


def export_file(bridge: "FileBridge", payload: dict, default_name: str,
                done: str) -> str:
    """Save dialog → atomic write → honest result JSON + log line."""
    path = pick_save_path("Export", default_name)
    if not path:
        bridge._log("⏹ Export cancelled", "warn")
        return _json({"ok": False, "canceled": True})
    result = write_export(path, payload)
    if result.is_err:
        return bridge._err(f"export failed: {result.err().detail}")
    bridge._log(f"📤 {done} → {path}", "success")
    done_payload = _json({"ok": True, "path": path})
    bridge.export_done.emit(done_payload)
    return done_payload


def import_file_result(bridge: "FileBridge", path: str,
                       expected: str) -> str:
    """Read + validate ONE file and hand the preview to the UI. Nothing
    in the app is touched — applying is a separate slot."""
    text = read_export_file(path)
    if text.is_err:
        return bridge._err(f"could not read the file: "
                           f"{text.err().detail}")
    parsed = parse_export(text.unwrap())
    if parsed.is_err:
        return bridge._err(parsed.err().detail)
    preview = parsed.unwrap()
    if preview.kind != expected:
        return bridge._err(f"that file is a {preview.kind} export, "
                           f"not a {expected} preset")
    for warning in preview.warnings:
        bridge._log(f"⚠ {warning}", "warn")
    payload = _json({"ok": True, **preview_dict(preview),
                     "text": text.unwrap()})
    bridge.import_preview.emit(payload)
    return payload


def revalidate(bridge: "FileBridge", preview_json: str):
    """Apply re-parses the RAW file text: a preview the UI (or a test)
    altered mid-flight is rejected, not applied (RULE 13)."""
    try:
        data = json.loads(preview_json or "{}")
    except json.JSONDecodeError:
        return None, bridge._err("the import payload is not JSON")
    if not isinstance(data, dict) or \
            not isinstance(data.get("text"), str):
        return None, bridge._err("the import payload is missing the "
                                 "file text")
    parsed = parse_export(data["text"])
    if parsed.is_err:
        return None, bridge._err(f"re-validation failed: "
                                 f"{parsed.err().detail}")
    return parsed.unwrap(), None


class FileBridge(QObject):
    """Export/import slots; the router re-publishes them on the wire."""

    export_done = Signal(str)          # JSON: {ok, path} | {ok:false,…}
    import_preview = Signal(str)       # JSON preview, before anything applies

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx

    # ── shared helpers ───────────────────────────────────────────
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
        payload = build_stack_export(name, blocks,
                                     _library_of(self.ctx.config))
        return export_file(self, payload,
                           _default_name(name, name == "stack"),
                           f"Exported “{name}” ({len(blocks)} blocks)")

    @Slot(str, result=str)
    def export_stack_preset(self, name: str) -> str:
        presets = self.ctx.presets
        blocks = presets.load_stack(name) if presets else None
        if blocks is None:
            return self._err(f"preset “{name}” not found")
        blocks = normalize_blocks(blocks)
        payload = build_stack_export(name, blocks,
                                     _library_of(self.ctx.config))
        return export_file(self, payload, _default_name(name),
                           f"Exported preset “{name}” "
                           f"({len(blocks)} blocks)")

    @Slot(str, result=str)
    def export_custom_block(self, name: str) -> str:
        name = (name or "").strip()
        entry = next((e for e in _library_of(self.ctx.config)
                      if isinstance(e, dict) and e.get("name") == name),
                     None)
        if entry is None:
            return self._err(f"block preset “{name}” not found")
        try:
            payload = build_block_export(name, entry.get("block") or {})
        except ValueError as exc:
            return self._err(str(exc))
        return export_file(self, payload, _default_name(name),
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
        return import_file_result(self, path, kind)

    @Slot(str, str, str, result=str)
    def apply_imported(self, preview_json: str, mode: str,
                       stack_json: str) -> str:
        preview, fail = revalidate(self, preview_json)
        if fail:
            return fail
        if preview.kind == "block":
            return apply_block(self, preview, mode)
        if mode not in ("replace", "merge") or preview.kind != "stack":
            return self._err("bad import payload (stack + replace/merge)")
        current = self._clean(stack_json)
        stack = current + list(preview.stack) if mode == "merge" \
            else list(preview.stack)
        added, replaced = merge_library(self, preview.custom_blocks)
        apply_stack(self, stack, current)
        saved_name = save_imported_preset(self, preview)
        payload = _json(_library_of(self.ctx.config))
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
