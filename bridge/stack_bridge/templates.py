"""Message template presets: save, load, list, delete.

`TemplatePresetMixin` owns the reusable message bodies beside the stack
presets. A failure is reported as the error it is — never as a success
line over an unchanged store.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Slot

from core.events import PresetsChanged

log = logging.getLogger("chatbot")


class TemplatePresetMixin:
    # ── message template presets ─────────────────────────────────
    def _emit_templates(self) -> None:
        payload = json.dumps(self.ctx.presets.list_templates(),
                             ensure_ascii=False)
        self.template_list_updated.emit(payload)
        self.ctx.bus.emit(PresetsChanged(kind="templates", payload=payload))

    @Slot(str, str)
    def save_template_preset(self, name, body):
        try:
            self.ctx.presets.save_template(name, body or "")
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Template save failed: {exc}", "error")
            return
        self._emit_templates()
        self._log(f"💾 Template “{name}” saved", "success")

    @Slot(str, result=str)
    def load_template_preset(self, name):
        body = self.ctx.presets.load_template(name)
        if body is None:
            self._log(f"❌ Template “{name}” not found", "error")
            return ""
        self.template_loaded.emit(name, body)
        self._log(f"📂 Template “{name}” loaded", "success")
        return body

    @Slot(result=str)
    def list_template_presets(self):
        try:
            return json.dumps(self.ctx.presets.list_templates(),
                              ensure_ascii=False)
        except Exception as exc:                        # noqa: BLE001
            log.error("list templates failed: %s", exc)
            return "[]"

    @Slot(str)
    def delete_template_preset(self, name):
        try:
            if self.ctx.presets.delete_template(name):
                self._emit_templates()
                self._log(f"🗑 Template “{name}” deleted", "warn")
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Template delete failed: {exc}", "error")
