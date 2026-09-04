"""Simple pause/delay action."""

import asyncio
import logging
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class Pause(BaseAction):
    block_id = "PAUSE"
    name = "Custom Pause"
    icon = "⏸️"

    def __init__(self, duration_ms: int = 1000, **kw):
        super().__init__(pre_delay_ms=0, **kw)
        self.duration_ms = duration_ms

    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        self.debug(f"⏸ Pausing {self.duration_ms} ms")
        log.info("Pausing %d ms", self.duration_ms)
        await asyncio.sleep(self.duration_ms / 1000.0)
        self.debug(f"✅ pause finished")
        return ActionResult.OK

    def config_schema(self) -> dict:
        return {"duration_ms": {"type": "number", "default": 1000, "label": "Duration (ms)"}}
