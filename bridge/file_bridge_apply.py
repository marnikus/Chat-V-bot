"""File bridge apply — extracted from file_bridge_orchestration (H-C5 split)

Apply stack/block/preset, ≤100 LOC.
"""

from __future__ import annotations

import logging

from bridge.file_bridge_dialogs import _json
from core.events import LogMessage, PresetsChanged, StackLoaded

log = logging.getLogger("chatbot")


def apply_stack(bridge: "FileBridge", stack: list[dict], current: list[dict]) -> None:
    if current and current != stack:
        bridge.ctx.undo.push_stack(current)
    engine = bridge.ctx.engine
    if engine is not None:
        engine.load_stack(list(stack))
    if bridge.ctx.config is not None:
        bridge.ctx.config.set_state(last_stack=list(stack), last_stack_preset="")
    bridge.ctx.bus.emit(StackLoaded(name="import", payload=_json(stack)))


def apply_block(bridge: "FileBridge", preview, mode: str) -> str:
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


def save_imported_preset(bridge: "FileBridge", preview):
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
