"""StackBridge — action stack run / presets / history."""

from __future__ import annotations

import asyncio
import json
import logging
from PySide6.QtCore import QObject, Signal, Slot
try:
    from qasync import asyncSlot
except Exception:
    asyncSlot = lambda *a, **kw: (lambda f: f)

log = logging.getLogger("chatbot")


class StackBridge(QObject):
    step_complete = Signal(str, str)
    step_started = Signal(int, str, str)
    stack_complete = Signal()
    log_message = Signal(str, str)
    preset_list_updated = Signal(str)
    template_list_updated = Signal(str)
    custom_blocks_updated = Signal(str)
    stack_loaded = Signal(str, str)
    history_changed = Signal()

    def __init__(self, ctx: dict, parent=None):
        super().__init__(parent)
        self._engine = ctx.get("engine")
        self._config = ctx.get("config")
        self._router = ctx.get("router")
        # preset store via config (will migrate to BlockStore)
        from backend.preset_store import PresetStore
        self._presets = PresetStore(config=self._config)
        try:
            self._presets.import_legacy()
        except Exception:
            pass
        if self._engine:
            try:
                self._engine.step_complete.connect(self.step_complete.emit)
                self._engine.step_started.connect(self.step_started.emit)
                self._engine.stack_complete.connect(self.stack_complete.emit)
                self._engine.log_msg.connect(lambda m: self.log_message.emit(m, "info"))
                self._engine.debug_msg.connect(lambda m, l: self.log_message.emit(m, l))
            except Exception:
                pass

    @Slot(str)
    def run_stack(self, stack_json):
        if self._engine.is_running:
            self.log_message.emit("⚠ Already running", "warn")
            return
        try:
            blocks = json.loads(stack_json)
        except json.JSONDecodeError:
            self.log_message.emit("❌ Bad JSON", "error")
            return
        self._engine.load_stack(blocks)
        asyncio.ensure_future(self._engine.execute())

    @Slot()
    def stop_stack(self): self._engine.stop()
    @Slot()
    def pause_stack(self): self._engine.pause()
    @Slot()
    def resume_stack(self): self._engine.resume()

    @Slot(result=str)
    def get_stack_json(self): return json.dumps(self._engine.get_stack(), ensure_ascii=False)

    # presets
    @Slot(str, str)
    def save_stack_preset(self, name, stack_json):
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            self.log_message.emit("❌ Preset save aborted", "error")
            return
        try:
            self._presets.save_stack(name, blocks)
        except Exception as exc:  # noqa: BLE001
            self.log_message.emit(f"❌ Preset save failed: {exc}", "error")
            return
        self.preset_list_updated.emit(json.dumps(self._presets.list_stacks(), ensure_ascii=False))
        self.log_message.emit(f"💾 Preset “{name}” saved", "success")

    @Slot(str, result=str)
    def load_stack_preset(self, name):
        blocks = self._presets.load_stack(name)
        if blocks is None:
            self.log_message.emit(f"❌ Preset “{name}” not found", "error")
            return "null"
        self._engine.load_stack(blocks)
        payload = json.dumps(blocks, ensure_ascii=False)
        self.stack_loaded.emit(name, payload)
        return payload

    @Slot(result=str)
    def list_stack_presets(self):
        try: return json.dumps(self._presets.list_stacks(), ensure_ascii=False)
        except Exception: return "[]"

    @Slot(str)
    def delete_stack_preset(self, name):
        try:
            if self._presets.delete_stack(name):
                self.preset_list_updated.emit(json.dumps(self._presets.list_stacks(), ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            self.log_message.emit(f"❌ Preset delete failed: {exc}", "error")

    # templates
    @Slot(str, str)
    def save_template_preset(self, name, body):
        try: self._presets.save_template(name, body or "")
        except Exception as exc:  # noqa: BLE001
            self.log_message.emit(f"❌ Template save failed: {exc}", "error"); return
        self.template_list_updated.emit(json.dumps(self._presets.list_templates(), ensure_ascii=False))

    @Slot(str, result=str)
    def load_template_preset(self, name):
        body = self._presets.load_template(name)
        if body is None: return ""
        return body

    @Slot(result=str)
    def list_template_presets(self):
        try: return json.dumps(self._presets.list_templates(), ensure_ascii=False)
        except Exception: return "[]"

    @Slot(str)
    def delete_template_preset(self, name):
        try:
            if self._presets.delete_template(name):
                self.template_list_updated.emit(json.dumps(self._presets.list_templates(), ensure_ascii=False))
        except Exception:
            pass
