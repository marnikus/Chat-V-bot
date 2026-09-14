"""PresetApplier — what importing a preset file actually DOES to the app.

Split out of `bridge/file_bridge.py` in Round I (step I3). That module was 332
lines at MI 37.5, and 8 of its module-level functions took a `bridge` argument
only to reach two things through it: `bridge.ctx` and `bridge._log`. That is a
collaborator wearing a parameter's clothes — the functions are not Qt work,
they need no QObject, and passing the whole bridge let any of them reach
anything on it.

So the pair `(ctx, log)` becomes an object, and the functions become its
methods. `FileBridge` keeps exactly the Qt-shaped work: native dialogs, the
`@Slot` surface, and emitting signals. Nothing here imports Qt, which is the
point — the apply path is now testable without a QObject or a QApplication.

Two methods, `export` and `preview`, return a `(result, emit)` pair rather
than emitting themselves: the Qt signal belongs to the bridge, and the
applier should not hold a reference to it just to fire it. `emit` is None
when there is nothing to announce (a cancel, or a failure).

The QWebChannel surface is unchanged by this split and is pinned against
regression by tests/unit/bridge/test_file_stack_bridge_wire_contract.py.
Design: docs/STACK_PRESET_EXPORT_IMPORT_DESIGN_2026-09-10.md §4.2.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from core.events import PresetsChanged, StackLoaded
from services.preset_io import (PresetPreview, parse_export, preview_dict,
                                read_export_file, write_export)

log = logging.getLogger("chatbot")


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


class PresetApplier:
    """Applies a validated preset preview to the config/engine/preset stores.

    Owns the two things the old module-level functions reached through
    `bridge`: the app context and the log sink. `log_cb` takes
    ``(message, level)`` — the bridge routes it onto the event bus.
    """

    def __init__(self, ctx, log_cb):
        self.ctx = ctx
        self._log_cb = log_cb

    # ── shared helpers ───────────────────────────────────────────
    def log(self, message: str, level: str = "info") -> None:
        self._log_cb(message, level)

    def err(self, detail: str) -> str:
        """Log a failure and render it as the UI's error JSON."""
        self.log(f"❌ {detail}", "error")
        return _json({"ok": False, "error": detail})

    def library(self) -> list[dict]:
        """Every custom block currently in the library ([] with no config)."""
        config = self.ctx.config
        return config.blocks.all() if config is not None else []

    # ── applying an import ───────────────────────────────────────
    def merge_library(self, entries) -> tuple[int, int]:
        """Merge imported custom blocks into the block library. Same name =
        same block: a collision overwrites, and both outcomes are counted
        for the log line."""
        if not entries or self.ctx.config is None:
            return 0, 0
        store = self.ctx.config.blocks
        items = store.all()
        added = replaced = 0
        for entry in entries:
            name = entry.get("name", "")
            existed = any(b.get("name") == name for b in items)
            # entries come from a re-validated preview: `block` is a dict
            result = store.save_custom_block(name, entry["block"])
            if result.is_err:
                self.log(f"⚠ Block “{name}” not saved: "
                         f"{result.err().detail}", "warn")
                continue
            if existed:
                replaced += 1
            else:
                added += 1
        if added or replaced:
            self.ctx.config.save()
        return added, replaced

    def apply_stack(self, stack: list[dict], current: list[dict]) -> None:
        """Load the new stack into the engine and persist it. The pre-import
        stack is pushed to the ONE global undo history (RULE 12)."""
        if current and current != stack:
            self.ctx.undo.push_stack(current)
        engine = self.ctx.engine
        if engine is not None:
            engine.load_stack(list(stack))
        if self.ctx.config is not None:
            self.ctx.config.set_state(last_stack=list(stack),
                                      last_stack_preset="")
        self.ctx.bus.emit(StackLoaded(name="import", payload=_json(stack)))

    def apply_block(self, preview: PresetPreview, mode: str) -> str:
        """Add one imported block to the library (mode "add" only)."""
        if mode != "add" or not isinstance(preview.block, dict):
            return self.err("a block file needs mode “add” with a block")
        if self.ctx.config is None:
            return self.err("no block library available")
        saved = self.ctx.config.blocks.save_custom_block(preview.name,
                                                         preview.block)
        if saved.is_err:
            return self.err("block library rejected the import: "
                            f"{saved.err().detail}")
        self.ctx.config.save()
        payload = _json(self.ctx.config.blocks.all())
        self.ctx.bus.emit(PresetsChanged(kind="custom_blocks",
                                         payload=payload))
        self.log(f"📥 Block “{preview.name}” added to the library",
                 "success")
        return _json({"ok": True, "name": preview.name})

    def save_imported_preset(self, preview: PresetPreview):
        """The imported file is also a named preset: register it in the
        saved-preset list so it shows up in Select Preset right away
        (same name = same preset: a re-import refreshes it)."""
        presets = self.ctx.presets
        if presets is None or not preview.stack:
            return False
        try:
            presets.save_stack(preview.name, list(preview.stack))
            saved = presets.save(force=True)
        except (ValueError, OSError) as exc:
            self.log(f"⚠ Imported preset not saved: {exc}", "warn")
            return False
        if not saved:
            self.log("⚠ Imported preset could not be persisted to disk",
                     "warn")
            return False
        payload = _json(presets.list_stacks())
        self.ctx.bus.emit(PresetsChanged(kind="stacks", payload=payload))
        return preview.name

    # ── reading and writing files ────────────────────────────────
    def export(self, path: Optional[str], payload: dict,
               done: str) -> tuple[str, Optional[str]]:
        """Atomic write → honest result JSON + log line.

        Returns ``(result_json, emit_payload)``; `emit_payload` is None
        unless the export succeeded and the bridge should announce it. The
        save dialog stays in the bridge: `path` arrives already chosen (or
        empty, when the user cancelled).
        """
        if not path:
            self.log("⏹ Export cancelled", "warn")
            return _json({"ok": False, "canceled": True}), None
        result = write_export(path, payload)
        if result.is_err:
            return self.err(f"export failed: {result.err().detail}"), None
        self.log(f"📤 {done} → {path}", "success")
        done_payload = _json({"ok": True, "path": path})
        return done_payload, done_payload

    def preview(self, path: str, expected: str) -> tuple[str, Optional[str]]:
        """Read + validate ONE file and describe it for the UI. Nothing
        in the app is touched — applying is a separate slot.

        Returns ``(result_json, emit_payload)`` like `export`.
        """
        text = read_export_file(path)
        if text.is_err:
            return self.err("could not read the file: "
                            f"{text.err().detail}"), None
        parsed = parse_export(text.unwrap())
        if parsed.is_err:
            return self.err(parsed.err().detail), None
        preview = parsed.unwrap()
        if preview.kind != expected:
            return self.err(f"that file is a {preview.kind} export, "
                            f"not a {expected} preset"), None
        for warning in preview.warnings:
            self.log(f"⚠ {warning}", "warn")
        payload = _json({"ok": True, **preview_dict(preview),
                         "text": text.unwrap()})
        return payload, payload

    def revalidate(self, preview_json: str):
        """Apply re-parses the RAW file text: a preview the UI (or a test)
        altered mid-flight is rejected, not applied (RULE 13)."""
        try:
            data = json.loads(preview_json or "{}")
        except json.JSONDecodeError:
            return None, self.err("the import payload is not JSON")
        if not isinstance(data, dict) or \
                not isinstance(data.get("text"), str):
            return None, self.err("the import payload is missing the "
                                  "file text")
        parsed = parse_export(data["text"])
        if parsed.is_err:
            return None, self.err(f"re-validation failed: "
                                  f"{parsed.err().detail}")
        return parsed.unwrap(), None
