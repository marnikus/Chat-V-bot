"""Type a message into the chat textarea (with debugger detail).

The block can send either its own stored text or — when the “use composer”
checkbox is on — the current text of the Message Composer window, which the
engine mirrors live (engine.composer_text, fed by Bridge.save_message).
"""

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

    def __init__(self, message: str = "", use_composer: bool = False,
                 typing_speed_ms: int = 30, pre_delay_ms: int = 500,
                 **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.message = message
        self.use_composer = bool(use_composer)
        self.typing_speed_ms = typing_speed_ms

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        if self.use_composer:
            composer_text = getattr(engine, "composer_text", "") or ""
            if not composer_text.strip():
                report = engine.report if engine else None
                if report:
                    report("⚠ Type Message: “Use Message Composer” is on but "
                           "the composer is empty — nothing typed", "warn")
                return ActionResult.FAIL
            text = composer_text
        else:
            text = self.message
        # {{nick}} → the remembered selected user (Click User) of this run;
        # falls back to the queued user of this step, as before.
        nick = user_nick
        if engine is not None:
            nick = getattr(engine, "selected_nick", "") or user_nick
        text = text.replace("{{nick}}", nick)
        report = engine.report if engine else None
        ok = await type_message(cdp, text, self.typing_speed_ms, report)
        return ActionResult.OK if ok else ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["use_composer"] = {"type": "bool", "default": False,
                             "label": "Use text from the Message Composer "
                                      "window (ignores the text below)"}
        s["message"] = {"type": "textarea", "default": "",
               "label": "Message text — {{nick}} = selected user"}
        s["typing_speed_ms"] = {"type": "number", "default": 30, "label": "Speed (ms/char)"}
        return s
