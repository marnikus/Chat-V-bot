"""File bridge IO — extracted from file_bridge_orchestration (H-C5 split)

Export/import/revalidate, ≤100 LOC.
"""

from __future__ import annotations

import json
import logging

from bridge.file_bridge_dialogs import _json, pick_save_path
from services.preset_io import parse_export, preview_dict, read_export_file, write_export

log = logging.getLogger("chatbot")


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
