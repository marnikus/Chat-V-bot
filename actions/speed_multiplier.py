"""Speed Multiplier — one coefficient scaling every wait of the run.

A control block, like Pause: it performs no click and takes no pre-delay
of its own; its `execute()` stamps the run's global wait-speed rate onto
the engine (1.0 = normal, 0.5 = every wait halved, 2.0 = every wait
doubled) and reports it. The engine resolves the same rate at run start
from the last enabled SPEED block in the stack, so the collect phase —
which runs before the per-user loop — scales too.

Design: docs/archive/2026-09-13-speed-multiplier/SPEED_MULTIPLIER_DESIGN_2026-09-13.md
"""

import logging
from typing import Optional

from actions.base import ActionResult, BlockField, MarkerBlock
from actions.speed import coerce_multiplier, describe
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class SpeedMultiplier(MarkerBlock):
    block_id = "SPEED_MULTIPLIER"
    name = "Speed Multiplier"
    icon = "⏩"

    FIELDS = (
        BlockField("multiplier", "number",
                   "Speed coefficient — 1.0 = normal",
                   clean=coerce_multiplier),
    )

    def __init__(self, multiplier: float = 1.0, **kw):
        super().__init__(multiplier=multiplier, **kw)

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        """Stamp this block's rate onto the run and say what it means."""
        value = coerce_multiplier(self.multiplier)
        if engine is not None:
            engine.speed_multiplier = value
            engine.report(f"⏩ Global wait speed {describe(value)}", "info")
        log.info("Speed multiplier applied: %s", describe(value))
        return ActionResult.OK
