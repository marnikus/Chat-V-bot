"""File bridge orchestration — extracted from file_bridge (H-C5 split)

Merge/apply/export/import logic, ≤200 LOC.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bridge.file_bridge_dialogs import _json, _library_of, pick_open_path, pick_save_path
from core.events import LogMessage, PresetsChanged, StackLoaded
from services.preset_io import (
    PresetPreview,
    parse_export,
    preview_dict,
    read_export_file,
    write_export,
)

log = logging.getLogger("chatbot")


def merge_library(bridge: "FileBridge", entries) -> "tuple[int, int]":
    if not entries or bridge.ctx.config is None:
        return 0, 0
    store = bridge.ctx.config.blocks
    items = store.all()
    added = replaced = 0
    for entry in entries:
        name = entry.get("name", "")
        existed = any(b.get("name") == name for b in items)
        result = store.save_custom_block(name, entry["block"])
        if result.is_err:
            bridge._log(f"⚠ Block “{name}” not saved: {result.err().detail}", "warn")
            continue
        if existed:
            replaced += 1
        else:
            added += 1
    if added or replaced:
        bridge.ctx.config.save()
    return added, replaced


def apply_stack(bridge: "FileBridge", stack: list[dict], current: list[dict]) -> None:
    if current and current != stack:
        bridge.ctx.undo.push_stack(current)
    engine = bridge.ctx.engine
    if engine is not None:
        engine.load_stack(list(stack))
    if bridge.ctx.config is not None:
        bridge.ctx.config.set_state(last_stack=list(stack), last_stack_preset="")
    bridge.ctx.bus.emit(StackLoaded(name="import", payload=_json(stack)))


def apply_block(bridge: "FileBridge", preview: PresetPreview, mode: str) -> str:
    if mode != "add" or not isinstance(preview.block, dict):
        return bridge._err("a block file needs mode “add” with a block")
    if bridge.ctx.config is None:
        return bridge._err("no block library available")
    saved = bridge.ctx.config.blocks.save_custom_block(preview.name, preview.block)
    if saved.is_err:
        return bridge._err("block library rejected the import: " f"{saved.err().detail}")
    bridge.ctx.config.save()
    payload = _json(bridge.ctx.config.blocks.all())
    bridge.ctx.bus.emit(PresetsChanged(kind="custom_blocks", payload=payload))
    bridge._log(f"📥 Block “{preview.name}” added to the library", "success")
    return _json({"ok": True, "name": preview.name})


def save_imported_preset(bridge: "FileBridge", preview: PresetPreview):
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
        bridge._log("⚠ Imported preset could not be persisted to disk", "warn")
        return False
    payload = _json(presets.list_stacks())
    bridge.ctx.bus.emit(PresetsChanged(kind="stacks", payload=payload))
    return preview.name


def export_file(bridge: "FileBridge", payload: dict, default_name: str, done: str) -> str:
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


def import_file_result(bridge: "FileBridge", path: str, expected: str) -> str:
    text = read_export_file(path)
    if text.is_err:
        return bridge._err(f"could not read the file: " f"{text.err().detail}")
    parsed = parse_export(text.unwrap())
    if parsed.is_err:
        return bridge._err(parsed.err().detail)
    preview = parsed.unwrap()
    if preview.kind != expected:
        return bridge._err(f"that file is a {preview.kind} export, " f"not a {expected} preset")
    for warning in preview.warnings:
        bridge._log(f"⚠ {warning}", "warn")
    payload = _json({"ok": True, **preview_dict(preview), "text": text.unwrap()})
    bridge.import_preview.emit(payload)
    return payload


def revalidate(bridge: "FileBridge", preview_json: str):
    try:
        data = json.loads(preview_json or "{}")
    except json.JSONDecodeError:
        return None, bridge._err("the import payload is not JSON")
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        return None, bridge._err("the import payload is missing the " "file text")
    parsed = parse_export(data["text"])
    if parsed.is_err:
        return None, bridge._err(f"re-validation failed: " f"{parsed.err().detail}")
    return parsed.unwrap(), None
