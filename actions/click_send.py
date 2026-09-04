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
        # Step1: check if send button exists
        has_btn = await cdp.evaluate(
            "!!document.querySelector(\"button[type='submit']\") || "
            "!!Array.from(document.querySelectorAll('mat-icon'))"
            ".find(i=>i.textContent.trim()==='send')")
        log.info("🔍 Send button present: %s", bool(has_btn))
        if not has_btn:
            log.error("❌ FAIL: send button not found on page")
            return ActionResult.FAIL
        ok = await click_send(cdp)
        if ok:
            log.info("✅ Send button clicked")
            return ActionResult.OK
        log.error("❌ FAIL: click_send() returned false")
        return ActionResult.FAIL
