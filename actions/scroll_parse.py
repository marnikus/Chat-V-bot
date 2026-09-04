"""Scroll & Parse Users action block — handled by the engine's parse phase.

The block itself is a marker: the engine executes the ScrollParser once
before the per-user loop and reports every scroll/probe step there.
"""

import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class ScrollParse(BaseAction):
    block_id = "SCROLL_PARSE"
    name = "Scroll & Parse Users"
    icon = "📜"

    def __init__(self, max_scrolls: int = 50, scroll_pause_ms: int = 800,
                 pre_delay_ms: int = 300, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.max_scrolls = max_scrolls
        self.scroll_pause_ms = scroll_pause_ms

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        if engine:
            engine.report(f"📜 SCROLL_PARSE (max={self.max_scrolls}, "
                          f"pause={self.scroll_pause_ms} ms) — runs in parse phase",
                          "info")
        log.info("Scroll parse block triggered (max=%d)", self.max_scrolls)
        return ActionResult.OK

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["max_scrolls"] = {"type": "number", "default": 50, "label": "Max scrolls"}
        s["scroll_pause_ms"] = {"type": "number", "default": 800, "label": "Pause (ms)"}
        return s
