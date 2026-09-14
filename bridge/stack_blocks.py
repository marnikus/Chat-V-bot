"""StackBridge custom Find & Click block-preset slots.

Split out of `bridge/stack_bridge` in Round I as a MIXIN — see
`bridge/stack_templates` for why a mixin and not a collaborator: these
`@Slot` names are the QWebChannel wire contract and must stay on the
derived QObject's metaobject.

These three slots plus `_emit_blocks` are the only members of `StackBridge`
that go through `ctx.config.blocks`; the preset slots next door go through
`ctx.presets` instead. That is the seam LCOM4 found, not one chosen to make
a line count work out.

Imports point one way: `stack_bridge` imports this; this imports only Qt,
`core` and the standard library.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Slot

from core.events import PresetsChanged

log = logging.getLogger("chatbot")


class StackBlocksMixin:
    """`list/save/delete_custom_block` and their emit helper."""

    def _emit_blocks(self) -> None:
        payload = json.dumps(self.ctx.config.blocks.all(),
                             ensure_ascii=False)
        self.custom_blocks_updated.emit(payload)
        self.ctx.bus.emit(PresetsChanged(kind="custom_blocks",
                                         payload=payload))

    @Slot(result=str)
    def list_custom_blocks(self):
        return json.dumps(self.ctx.config.blocks.all(), ensure_ascii=False)

    @Slot(str, str)
    def save_custom_block(self, name, block_json):
        name = (name or "").strip()
        try:
            block = json.loads(block_json or "{}")
        except json.JSONDecodeError:
            self._log("❌ Block preset save aborted: bad JSON", "error")
            return
        if not isinstance(block, dict) or not name:
            self._log("❌ Block preset needs a name and block config",
                      "error")
            return
        result = self.ctx.config.blocks.save_custom_block(name, block)
        if result.is_err:
            err_ = result.err()
            self._log(f"❌ Block preset save failed: "
                      f"{err_.detail or err_.code}", "error")
            return
        self.ctx.config.save()
        self._emit_blocks()
        self._log(f"💾 Block preset “{name}” saved — reusable from "
                  "the + Add menu and Custom Blocks chips", "success")

    @Slot(str)
    def delete_custom_block(self, name):
        before = len(self.ctx.config.blocks.all())
        self.ctx.config.blocks.delete_custom_block(name)
        if len(self.ctx.config.blocks.all()) != before:
            self.ctx.config.save()
            self._emit_blocks()
            self._log(f"🗑 Block preset “{name}” removed", "warn")
        else:
            self._log(f"⚠ Block preset “{name}” not found", "warn")
