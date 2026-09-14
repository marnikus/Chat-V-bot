"""StackBridge message-template preset slots.

Split out of `bridge/stack_bridge` in Round I as a MIXIN, for the same reason
HistoryBridge's slots were in H1: QWebChannel exposes ONE object, so every
`@Slot` name below is part of the wire contract and the class identity has to
survive the split. A collaborator object would have moved these names off the
metaobject and silently broken the frontend.

Why these four belong together and away from the rest: measured with LCOM4
over `StackBridge`, discounting the ubiquitous `ctx`/`_log`, the class fell
into 21 components. Templates were one of the few real clusters — the four
methods here share `_emit_templates` and `template_loaded` and touch nothing
else in the class. Nothing else reaches into them.

Imports point one way: `stack_bridge` imports this; this imports only Qt,
`core` and the standard library.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Slot

from core.events import PresetsChanged

log = logging.getLogger("chatbot")


class StackTemplateMixin:
    """`save/load/list/delete_template_preset` and their emit helper."""

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
