"""Click the send button to submit the message.

Uses the shared visual-confirmation runner (RED outline on the element found,
pause, ORANGE outline on the click target, then click) per docs/AGENT_RULES.md.
Falls back to the mat-icon 'send' button when the submit button is absent.
"""

import logging
from typing import Optional

from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.message_injector import SEND_SELECTOR
from backend.visual_click import find_and_click

log = logging.getLogger("chatbot")

#: Fallback: the button wrapping a mat-icon whose text is exactly "send".
SEND_ICON_SELECTOR = "button:has(mat-icon)"


class ClickSend(BaseAction):
    block_id = "CLICK_SEND"
    name = "Click Send"
    icon = "📨"

    def __init__(self, selector: str = SEND_SELECTOR,
                 fallback_selector: str = SEND_ICON_SELECTOR,
                 fallback_text: str = "send",
                 highlight_enabled: bool = True, confirm_pause_ms: int = 700,
                 pre_delay_ms: int = 300, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.selector = selector
        self.fallback_selector = fallback_selector
        self.fallback_text = fallback_text
        self.highlight_enabled = bool(highlight_enabled)
        self.confirm_pause_ms = max(0, int(confirm_pause_ms))

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        outcome = await find_and_click(
            cdp,
            selector=self.selector,
            highlight_enabled=self.highlight_enabled,
            confirm_pause_ms=self.confirm_pause_ms,
            label="send button",
            engine=engine,
        )
        if outcome == ActionResult.OK:
            return outcome

        if not self.fallback_selector:
            return outcome
        if engine:
            engine.report("↩ Submit button did not work — trying the "
                          f"mat-icon '{self.fallback_text}' fallback", "warn")
        return await find_and_click(
            cdp,
            selector=self.fallback_selector,
            label_selector="mat-icon",
            match_text=self.fallback_text,
            highlight_enabled=self.highlight_enabled,
            confirm_pause_ms=self.confirm_pause_ms,
            label=f"send icon “{self.fallback_text}”",
            engine=engine,
        )

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["selector"] = {"type": "text", "default": SEND_SELECTOR,
                         "label": "Send button selector (CSS)"}
        s["fallback_selector"] = {"type": "text", "default": SEND_ICON_SELECTOR,
                                  "label": "Fallback button selector (CSS)"}
        s["fallback_text"] = {"type": "text", "default": "send",
                              "label": "Fallback icon text"}
        s["highlight_enabled"] = {"type": "checkbox", "default": True,
                                  "label": "Draw confirmation outlines"}
        s["confirm_pause_ms"] = {"type": "number", "default": 700,
                                 "label": "Pause after found (ms)"}
        return s
