"""Wait for a target element to appear in the DOM."""

import asyncio
import logging
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")

TEXTAREA_SEL = "textarea[placeholder='Сообщение']"


class WaitPageLoad(BaseAction):
    block_id = "WAIT_PAGE_LOAD"
    name = "Wait for Page"
    icon = "⏳"

    def __init__(self, target_selector: str = "", timeout_ms: int = 5000,
                 pre_delay_ms: int = 200, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.target_selector = target_selector or TEXTAREA_SEL
        self.timeout_ms = timeout_ms

    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        await self.pre_delay()
        log.info("⏳ Waiting for '%s' (timeout %dms)...", self.target_selector, self.timeout_ms)
        deadline = asyncio.get_event_loop().time() + self.timeout_ms / 1000
        elapsed = 0
        while asyncio.get_event_loop().time() < deadline:
            result = await cdp.evaluate(
                f"!!document.querySelector('{self.target_selector}')")
            if result:
                elapsed = int((deadline - asyncio.get_event_loop().time()) * 1000)
                log.info("✅ Element found after ~%dms: '%s'",
                         self.timeout_ms - elapsed, self.target_selector)
                return ActionResult.OK
            await asyncio.sleep(0.3)
        log.error("❌ TIMEOUT after %dms: element '%s' not found",
                  self.timeout_ms, self.target_selector)
        return ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["target_selector"] = {"type": "text", "default": TEXTAREA_SEL,
                                "label": "Target selector"}
        s["timeout_ms"] = {"type": "number", "default": 5000, "label": "Timeout (ms)"}
        return s
