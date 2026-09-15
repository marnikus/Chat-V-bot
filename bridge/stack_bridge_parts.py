"""Stack bridge parts — facade (H-C5 split)

Now ≤50 LOC via run/composer/presets/blocks split.
"""

from __future__ import annotations

from bridge.stack_bridge_blocks import CustomBlocks
from bridge.stack_bridge_composer import Composer
from bridge.stack_bridge_presets import StackPresets, TemplatePresets
from bridge.stack_bridge_run import RunControl


class StackBridgeParts:
    def __init__(self, host):
        self._host = host
        self.run = RunControl(host)
        self.composer = Composer(host)
        self.presets = StackPresets(host)
        self.templates = TemplatePresets(host)
        self.blocks = CustomBlocks(host)

    def on_presets(self, event) -> None:
        host = self._host
        if event.kind == "stacks":
            host.preset_list_updated.emit(event.payload or "[]")
        elif event.kind == "templates":
            host.template_list_updated.emit(event.payload or "[]")
        elif event.kind == "custom_blocks":
            host.custom_blocks_updated.emit(event.payload or "[]")
