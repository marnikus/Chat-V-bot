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
        ok = await click_send(cdp)
        return ActionResult.OK if ok else ActionResult.FAIL
