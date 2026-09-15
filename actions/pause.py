"""Simple pause/delay action.

The one block that waits on purpose: it sleeps for its own `duration_ms` and
therefore never takes a pre-delay as well (an old preset's `pre_delay_ms` is
dropped, exactly like the other marker blocks).
"""

import asyncio
import logging

from typing import Optional

from actions.base import ActionResult, BlockField, MarkerBlock
from actions.speed import scale_ms
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class Pause(MarkerBlock):
    block_id = "PAUSE"
    name = "Custom Pause"
    icon = "⏸️"

    FIELDS = (
        BlockField("duration_ms", "number", "Duration (ms)"),
    )

    def __init__(self, duration_ms: int = 1000, **kw):
        super().__init__(duration_ms=duration_ms, **kw)

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        wait_ms = scale_ms(self.duration_ms, engine)
        if engine:
            engine.report(f"⏸ Pausing for {wait_ms} ms", "info")
        log.info("Pausing %d ms", wait_ms)
        await asyncio.sleep(wait_ms / 1000.0)
        if engine:
            engine.report("⏸ Pause finished", "info")
        return ActionResult.OK
