"""Configurable "Find & Click" block (CUSTOM_FIND).

A generic, reusable search-and-click action:
  * `selector`        — CSS selector of the element to find (the clickable
                        "rectangle", e.g. div[role='tab'].tab-item).
  * `label_selector`  — CSS selector of the element INSIDE the found element
                        whose text we search (e.g. p.chat-title).
  * `match_text`      — text to find inside the label element (empty = first).
  * `click_enabled`   — whether to click the element after it is found.
  * `click_selector`  — optional element INSIDE to click (empty = click the
                        found element itself).
  * `custom_name`     — user-friendly name shown in the stack and logs.

The block is a constructor: every instance can be customised through the UI
config panel and saved as a reusable preset.
"""

import json
import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.dom_probe import build_probe, interpret, interpret_wait, MATCH_CONTAINS

log = logging.getLogger("chatbot")


class CustomFind(BaseAction):
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, custom_name: str = "", selector: str = "",
                 label_selector: str = "", match_text: str = "",
                 click_enabled: bool = True, click_selector: str = "",
                 pre_delay_ms: int = 500, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.custom_name = custom_name or ""
        self.selector = selector or ""
        self.label_selector = label_selector or ""
        self.match_text = match_text or ""
        self.click_enabled = bool(click_enabled)
        self.click_selector = click_selector or ""

    def _label(self) -> str:
        """Human-readable search description used in logs."""
        parts = [f"element '{self.selector}'"]
        if self.label_selector:
            parts.append(f"text inside '{self.label_selector}'")
        if self.match_text:
            parts.append(f"matching \"{self.match_text}\"")
        return " ".join(parts)

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        if not self.selector:
            if engine:
                engine.report("❌ CUSTOM_FIND: `selector` is empty — configure "
                              "the block first", "error")
            return ActionResult.FAIL
        if engine:
            engine.report(f"🔍 Searching {self._label()}", "info")
        probe = build_probe(
            selector=self.selector,
            label_selector=self.label_selector or None,
            match_text=self.match_text or None,
            match_mode=MATCH_CONTAINS,
            click=bool(self.click_enabled),
            click_selector=self.click_selector or None,
            click_root=not bool(self.click_selector),
        )
        try:
            raw = await cdp.evaluate(probe)
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
                engine.report(f"❌ Failed to find element: {self._label()} — "
                              "no data returned (page context unavailable?)",
                              "error")
            return ActionResult.FAIL
        if engine:
            engine.report(f"🔍 Search result: selector matched "
                          f"{int(res.get('total', 0) or 0)} node(s)", "info")
        if not res.get("found"):
            msg, level = interpret(res, self._label())
            if engine:
                engine.report(msg, level)
            log.warning("CustomFind failed: %s", self._label())
            return ActionResult.FAIL
        if self.click_enabled:
            msg, level = interpret(res, self._label())
            if engine:
                engine.report(msg, level)
            if res.get("clicked"):
                log.info("CustomFind clicked: %s", self._label())
                return ActionResult.OK
            return ActionResult.FAIL
        # find-only mode
        msg, level = interpret_wait(res, self._label())
        if engine:
            engine.report(msg, level)
        log.info("CustomFind verified: %s", self._label())
        return ActionResult.OK if res.get("found") else ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["custom_name"] = {"type": "text", "default": "",
                            "label": "Block name (shown in stack)"}
        s["selector"] = {"type": "text", "default": "",
                         "label": "Element to find (CSS)"}
        s["label_selector"] = {"type": "text", "default": "",
                               "label": "Text element inside (CSS)"}
        s["match_text"] = {"type": "text", "default": "",
                           "label": "Text to match inside (optional)"}
        s["click_enabled"] = {"type": "checkbox", "default": True,
                              "label": "Click after found"}
        s["click_selector"] = {"type": "text", "default": "",
                               "label": "Element inside to click (optional)"}
        return s
