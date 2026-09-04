"""Click the send button to submit the message (with debugger detail)."""

import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.message_injector import click_send

log = logging.getLogger("chatbot")


class ClickSend(BaseAction):
    block_id = "CLICK_SEND"
    name = "Click Send"
    icon = "📨"

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        report = engine.report if engine else None
        ok = await click_send(cdp, report)
        return ActionResult.OK if ok else ActionResult.FAIL
