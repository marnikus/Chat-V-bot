"""🔁 Loop Marker: repeat the following blocks (until the next loop marker).

The executor handles this block type; `execute` is only a defensive fallback.
"""
from __future__ import annotations

from .base import BaseExecutor, BlockResult
from .registry import register


@register
class LoopMarker(BaseExecutor):
    action_type = "loop"
    label = "Loop Marker"
    icon = "🔁"
    params_schema = [{"key": "iterations", "label": "Iterations", "type": "number",
                      "default": 3, "min": 1, "max": 100}]

    async def execute(self, ctx, block) -> BlockResult:
        return BlockResult(data={"handled_by_executor": True})
