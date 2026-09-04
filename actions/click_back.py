"""Click back to the main room tab to return from private chat.

Same debugger contract as ClickMainTab: reports the element search result,
clickability of the found tab, and the click outcome step by step.
"""

import json
import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.dom_probe import build_probe, interpret

log = logging.getLogger("chatbot")


class ClickBack(BaseAction):
    block_id = "CLICK_BACK"
    name = "Return to Main"
    icon = "🔙"

    def __init__(self, selector: str = "div[role='tab'].tab-item",
                 child_selector: str = "p.chat-title",
                 tab_name: str = "Гостиная",
                 pre_delay_ms: int = 800, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.selector = selector
        self.child_selector = child_selector
        self.tab_name = tab_name

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        label = f"back tab “{self.tab_name}”"
        if engine:
            engine.report(f"🔍 Searching {label}: selector '{self.selector}'"
                          f" (child '{self.child_selector}')", "info")
        try:
            raw = await cdp.evaluate(build_probe(
                selector=self.selector, label_selector=self.child_selector,
                match_text=self.tab_name, click=True, click_root=True))
        except Exception as exc:
            if engine:
                engine.report(f"❌ CDP error during element search: {exc}", "error")
            return ActionResult.FAIL
        try:
            res = json.loads(raw) if raw else None
        except (json.JSONDecodeError, TypeError):
            res = None
        if not res:
            if engine:
                engine.report(f"❌ Failed to find element: {label} — no data returned "
                              "(page context unavailable?)", "error")
            return ActionResult.FAIL
        total = int(res.get("total", 0))
        if engine:
            engine.report(f"🔍 Search result: selector matched {total} tab node(s)",
                          "info")
        if not res.get("found"):
            msg, level = interpret(res, label)
            if engine:
                engine.report(msg, level)
            log.error("Back tab not found: '%s'", self.tab_name)
            return ActionResult.FAIL
        msg, level = interpret(res, label)
        if engine:
            engine.report(msg, level)
        if res.get("clicked"):
            log.info("Returned to tab '%s'", self.tab_name)
            return ActionResult.OK
        return ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["selector"] = {"type": "text", "default": "div[role='tab'].tab-item",
                         "label": "Tab element selector"}
        s["child_selector"] = {"type": "text", "default": "p.chat-title",
                               "label": "Child text selector"}
        s["tab_name"] = {"type": "text", "default": "Гостиная",
                         "label": "Tab name (text match)"}
        return s
