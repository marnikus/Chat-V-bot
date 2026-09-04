"""Type a message into the chat textarea (with debugger detail)."""

import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.message_injector import type_message

log = logging.getLogger("chatbot")


class TypeMessage(BaseAction):
    block_id = "TYPE_MESSAGE"
    name = "Type Message"
    icon = "⌨️"

    def __init__(self, message: str = "", typing_speed_ms: int = 30,
                 pre_delay_ms: int = 500, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.message = message
        self.typing_speed_ms = typing_speed_ms

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        text = self.message.replace("{{nick}}", user_nick)
        report = engine.report if engine else None
        ok = await type_message(cdp, text, self.typing_speed_ms, report)
        return ActionResult.OK if ok else ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["message"] = {"type": "textarea", "default": "", "label": "Message text"}
        s["typing_speed_ms"] = {"type": "number", "default": 30, "label": "Speed (ms/char)"}
        return s
