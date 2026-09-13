"""Stack presets: save, load, list, delete.

`StackPresetMixin` owns the named stack presets in the preset store. A
save or a load also remembers the stack as the current one and pushes
the previous stack onto the ONE global undo timeline (RULE 12), so the
chips and Ctrl+Z agree about what happened.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Slot

from core.events import PresetsChanged

log = logging.getLogger("chatbot")


class StackPresetMixin:
    # ── stack presets ────────────────────────────────────────────
    def _remember_stack(self, name: str, blocks: list[dict]) -> None:
        self.ctx.config.set_state(last_stack=blocks, last_stack_preset=name)
        self.ctx.undo.push_stack(blocks)

    def _emit_presets(self) -> None:
        payload = json.dumps(self.ctx.presets.list_stacks(),
                             ensure_ascii=False)
        self.preset_list_updated.emit(payload)
        self.ctx.bus.emit(PresetsChanged(kind="stacks", payload=payload))

    @Slot(str, str)
    def save_stack_preset(self, name, stack_json):
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            self._log("❌ Preset save aborted: stack is not valid JSON",
                      "error")
            return
        if not isinstance(blocks, list):
            self._log("❌ Preset save aborted: bad stack payload", "error")
            return
        blocks = self._clean_blocks(blocks)
        try:
            self.ctx.presets.save_stack(name, blocks)
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Preset save failed: {exc}", "error")
            return
        try:
            self.ctx.presets.save(force=True)
        except Exception:
            pass
        self._remember_stack(name, blocks)
        self._emit_presets()
        self._log(
            f"💾 Preset “{name}” saved ({len(blocks)} block(s)) — reload "
            f"anytime from the preset chips", "success")

    @Slot(str, result=str)
    def load_stack_preset(self, name):
        blocks = self.ctx.presets.load_stack(name)
        if blocks is None:
            self._log(f"❌ Preset “{name}” not found", "error")
            return "null"
        blocks = self._clean_blocks(blocks)
        # Preserve current stack in history before overwriting
        try:
            current = self.ctx.config.get_state("last_stack", None)
            if isinstance(current, list) and current:
                if current != blocks:
                    self.ctx.undo.push_stack(current)
        except Exception:                               # noqa: BLE001
            pass
        self.ctx.engine.load_stack(blocks)
        self._remember_stack(name, blocks)
        payload = json.dumps(blocks, ensure_ascii=False)
        self.stack_loaded.emit(name, payload)
        self._log(f"📂 Preset “{name}” loaded — {len(blocks)} block(s) "
                  "restored (↩ Undo to return to previous)", "success")
        return payload

    @Slot(result=str)
    def list_stack_presets(self):
        try:
            return json.dumps(self.ctx.presets.list_stacks(),
                              ensure_ascii=False)
        except Exception as exc:                        # noqa: BLE001
            log.error("list presets failed: %s", exc)
            return "[]"

    @Slot(str)
    def delete_stack_preset(self, name):
        try:
            if self.ctx.presets.delete_stack(name):
                self._emit_presets()
                self._log(f"🗑 Preset “{name}” deleted", "warn")
            else:
                self._log(f"⚠ Preset “{name}” not found", "warn")
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Preset delete failed: {exc}", "error")
