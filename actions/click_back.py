"""Click back to the main room tab to return from private chat.

Same two-phase visual confirmation as ClickMainTab: a RED outline on the
element found, a pause, then an ORANGE outline on the click target and the
click itself — each phase logged separately.
"""

import logging
from typing import Optional
from actions.base_action import BaseAction
from actions.find_click_runner import find_and_click
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class ClickBack(BaseAction):
    block_id = "CLICK_BACK"
    name = "Return to Main"
    icon = "🔙"

    def __init__(self, selector: str = "div[role='tab'].tab-item",
                 child_selector: str = "p.chat-title",
                 tab_name: str = "Гостиная",
                 highlight_enabled: bool = True, confirm_pause_ms: int = 700,
                 pre_delay_ms: int = 800, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.selector = selector
        self.child_selector = child_selector
        self.tab_name = tab_name
        self.highlight_enabled = bool(highlight_enabled)
        self.confirm_pause_ms = max(0, int(confirm_pause_ms or 0))

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        return await find_and_click(
            cdp,
            selector=self.selector,
            label_selector=self.child_selector,
            match_text=self.tab_name,
            click_enabled=True,
            highlight_enabled=self.highlight_enabled,
            confirm_pause_ms=self.confirm_pause_ms,
            label=f"back tab “{self.tab_name}”",
            engine=engine,
        )

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["selector"] = {"type": "text", "default": "div[role='tab'].tab-item",
                         "label": "Tab element selector"}
        s["child_selector"] = {"type": "text", "default": "p.chat-title",
                               "label": "Child text selector"}
        s["tab_name"] = {"type": "text", "default": "Гостиная",
                         "label": "Tab name (text match)"}
        s["highlight_enabled"] = {"type": "checkbox", "default": True,
                                  "label": "Draw confirmation outlines"}
        s["confirm_pause_ms"] = {"type": "number", "default": 700,
                                 "label": "Pause after found (ms)"}
        return s
