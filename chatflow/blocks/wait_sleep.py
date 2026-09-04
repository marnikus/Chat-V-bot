"""⏸ Wait / Sleep: explicit pause (in addition to per-block delay)."""
from __future__ import annotations

import asyncio

from ..engine.errors import StopRequested
from .base import BaseExecutor, BlockResult
from .registry import register


@register
class WaitSleep(BaseExecutor):
    action_type = "wait"
    label = "Wait / Sleep"
    icon = "⏸"
    params_schema = [{"key": "seconds", "label": "Seconds", "type": "number",
                      "default": 2, "min": 0, "max": 600}]

    async def execute(self, ctx, block) -> BlockResult:
        try:
            secs = float(block.params.get("seconds", 2))
        except (TypeError, ValueError):
            secs = 2.0
        secs = max(0.0, min(secs, 600.0))
        # sleep in 1s slices so STOP is honoured promptly
        remaining = secs
        while remaining > 0:
            if ctx.stopped():
                raise StopRequested
            step = min(1.0, remaining)
            await asyncio.sleep(step)
            remaining -= step
        if secs:
            ctx.log(self.icon, f"Waited {secs:.1f}s")
        return BlockResult()
