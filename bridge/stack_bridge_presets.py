"""Stack bridge presets — extracted from stack_bridge_parts (H-C5 split)

Stack and template presets, ≤150 LOC.
"""

from __future__ import annotations

import json
import logging

from bridge.stack_bridge_run import _Part, clean_blocks
from core.events import LogMessage, PresetsChanged

log = logging.getLogger("chatbot")


class StackPresets(_Part):
    def _remember(self, name: str, blocks: list[dict]) -> None:
        self._ctx.config.set_state(last_stack=blocks, last_stack_preset=name)
        self._ctx.undo.push_stack(blocks)

    def _emit(self) -> None:
        payload = json.dumps(self._ctx.presets.list_stacks(), ensure_ascii=False)
        self._host.preset_list_updated.emit(payload)
        self._ctx.bus.emit(PresetsChanged(kind="stacks", payload=payload))

    def save(self, name, stack_json) -> None:
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            self._log("❌ Preset save aborted: stack is not valid JSON", "error")
            return
        if not isinstance(blocks, list):
            self._log("❌ Preset save aborted: bad stack payload", "error")
            return
        blocks = clean_blocks(blocks)
        try:
            self._ctx.presets.save_stack(name, blocks)
        except Exception as exc:
            self._log(f"❌ Preset save failed: {exc}", "error")
            return
        try:
            self._ctx.presets.save(force=True)
        except Exception:
            pass
        self._remember(name, blocks)
        self._emit()
        self._log(f"💾 Preset “{name}” saved ({len(blocks)} block(s)) — reload anytime from the preset chips", "success")

    def load(self, name) -> str:
        blocks = self._ctx.presets.load_stack(name)
        if blocks is None:
            self._log(f"❌ Preset “{name}” not found", "error")
            return "null"
        blocks = clean_blocks(blocks)
        try:
            current = self._ctx.config.get_state("last_stack", None)
            if isinstance(current, list) and current:
                if current != blocks:
                    self._ctx.undo.push_stack(current)
        except Exception:
            pass
        self._ctx.engine.load_stack(blocks)
        self._remember(name, blocks)
        payload = json.dumps(blocks, ensure_ascii=False)
        self._host.stack_loaded.emit(name, payload)
        self._log(f"📂 Preset “{name}” loaded — {len(blocks)} block(s) restored (↩ Undo to return to previous)", "success")
        return payload

    def list_json(self) -> str:
        try:
            return json.dumps(self._ctx.presets.list_stacks(), ensure_ascii=False)
        except Exception as exc:
            log.error("list presets failed: %s", exc)
            return "[]"

    def delete(self, name) -> None:
        try:
            if self._ctx.presets.delete_stack(name):
                self._emit()
                self._log(f"🗑 Preset “{name}” deleted", "warn")
            else:
                self._log(f"⚠ Preset “{name}” not found", "warn")
        except Exception as exc:
            self._log(f"❌ Preset delete failed: {exc}", "error")


class TemplatePresets(_Part):
    def _emit(self) -> None:
        payload = json.dumps(self._ctx.presets.list_templates(), ensure_ascii=False)
        self._host.template_list_updated.emit(payload)
        self._ctx.bus.emit(PresetsChanged(kind="templates", payload=payload))

    def save(self, name, body) -> None:
        try:
            self._ctx.presets.save_template(name, body or "")
        except Exception as exc:
            self._log(f"❌ Template save failed: {exc}", "error")
            return
        self._emit()
        self._log(f"💾 Template “{name}” saved", "success")

    def load(self, name) -> str:
        body = self._ctx.presets.load_template(name)
        if body is None:
            self._log(f"❌ Template “{name}” not found", "error")
            return ""
        self._host.template_loaded.emit(name, body)
        self._log(f"📂 Template “{name}” loaded", "success")
        return body

    def list_json(self) -> str:
        try:
            return json.dumps(self._ctx.presets.list_templates(), ensure_ascii=False)
        except Exception as exc:
            log.error("list templates failed: %s", exc)
            return "[]"

    def delete(self, name) -> None:
        try:
            if self._ctx.presets.delete_template(name):
                self._emit()
                self._log(f"🗑 Template “{name}” deleted", "warn")
        except Exception as exc:
            self._log(f"❌ Template delete failed: {exc}", "error")
