"""Stack bridge custom blocks — extracted from stack_bridge_parts (H-C5 split)

≤100 LOC.
"""

from __future__ import annotations

import json
import logging

from bridge.stack_bridge_run import _Part
from core.events import PresetsChanged

log = logging.getLogger("chatbot")


class CustomBlocks(_Part):
    def _emit(self) -> None:
        payload = json.dumps(self._ctx.config.blocks.all(), ensure_ascii=False)
        self._host.custom_blocks_updated.emit(payload)
        self._ctx.bus.emit(PresetsChanged(kind="custom_blocks", payload=payload))

    def list_json(self) -> str:
        return json.dumps(self._ctx.config.blocks.all(), ensure_ascii=False)

    def save(self, name, block_json) -> None:
        name = (name or "").strip()
        try:
            block = json.loads(block_json or "{}")
        except json.JSONDecodeError:
            self._log("❌ Block preset save aborted: bad JSON", "error")
            return
        if not isinstance(block, dict) or not name:
            self._log("❌ Block preset needs a name and block config", "error")
            return
        result = self._ctx.config.blocks.save_custom_block(name, block)
        if result.is_err:
            err_ = result.err()
            self._log(f"❌ Block preset save failed: {err_.detail or err_.code}", "error")
            return
        self._ctx.config.save()
        self._emit()
        self._log(f"💾 Block preset “{name}” saved — reusable from the + Add menu and Custom Blocks chips", "success")

    def delete(self, name) -> None:
        before = len(self._ctx.config.blocks.all())
        self._ctx.config.blocks.delete_custom_block(name)
        if len(self._ctx.config.blocks.all()) != before:
            self._ctx.config.save()
            self._emit()
            self._log(f"🗑 Block preset “{name}” removed", "warn")
        else:
            self._log(f"⚠ Block preset “{name}” not found", "warn")
