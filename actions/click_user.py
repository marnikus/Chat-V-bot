"""Click a user by nickname in the user list (exact text match).

Reports, step by step: whether the user-item list was found, whether the
exact-nickname element was found, whether it was clickable, and whether the
click on .user-container succeeded.
"""

import json
import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.dom_probe import build_probe, interpret, MATCH_EXACT

log = logging.getLogger("chatbot")


class ClickUser(BaseAction):
    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, pre_delay_ms: int = 1000, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        label = f"user “{user_nick}”"
        if engine:
            engine.report(f"🔍 Searching {label}: selector 'user-item' with exact"
                          " match on '.primary-text'", "info")
        try:
            raw = await cdp.evaluate(build_probe(
                selector="user-item", label_selector=".primary-text",
                match_text=user_nick, match_mode=MATCH_EXACT,
                click=True, click_selector=".user-container"))
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
            engine.report(f"🔍 Search result: user-item list contains {total} row(s)",
                          "info")
        if not res.get("found"):
            msg, level = interpret(res, label)
            if engine:
                engine.report(msg, level)
            log.warning("User not found in list: %s", user_nick)
            return ActionResult.FAIL
        msg, level = interpret(res, label)
        if engine:
            engine.report(msg, level)
        if res.get("clicked"):
            log.info("Clicked user: %s", user_nick)
            return ActionResult.OK
        return ActionResult.FAIL
