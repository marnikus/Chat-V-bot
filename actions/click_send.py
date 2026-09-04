"""Click the send button to submit the message."""

import logging
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.message_injector import click_send

log = logging.getLogger("chatbot")


class ClickSend(BaseAction):
    block_id = "CLICK_SEND"
    name = "Click Send"
    icon = "📨"

    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        await self.pre_delay()
        self.debug("📨 Clicking send button (button[type='submit'] / mat-icon send)")
        ok = await click_send(cdp)
        if ok:
            self.debug("✅ send button found and clicked")
            return ActionResult.OK
        self.debug("❌ search failed: send button not found / click did not proceed")
        return ActionResult.FAIL
