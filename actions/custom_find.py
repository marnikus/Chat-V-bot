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
  * `highlight_enabled` — draw the visual confirmation outlines.
  * `confirm_pause_ms`  — pause after the find phase so the user can look.
  * `highlight_ms`      — how long each outline stays on screen.

Execution is split into two visible phases:

  1. FIND  — logs success/failure and draws a thin RED outline on the detected
     element, then pauses so the user can confirm it is the right one.
  2. CLICK — logs whether the element is clickable, draws a thin ORANGE outline
     over the click target area, then performs the click.

The block is a constructor: every instance can be customised through the UI
config panel and saved as a reusable preset.
"""

import logging
from typing import Optional
from actions.base_action import BaseAction
from actions.find_click_runner import find_and_click
from backend.cdp_client import CDPClient
from backend.dom_probe import MATCH_CONTAINS

log = logging.getLogger("chatbot")


class CustomFind(BaseAction):
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, custom_name: str = "", selector: str = "",
                 label_selector: str = "", match_text: str = "",
                 click_enabled: bool = True, click_selector: str = "",
                 highlight_enabled: bool = True, confirm_pause_ms: int = 700,
                 highlight_ms: int = 1200,
                 pre_delay_ms: int = 500, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.custom_name = custom_name or ""
        self.selector = selector or ""
        self.label_selector = label_selector or ""
        self.match_text = match_text or ""
        self.click_enabled = bool(click_enabled)
        self.click_selector = click_selector or ""
        self.highlight_enabled = bool(highlight_enabled)
        self.confirm_pause_ms = max(0, int(confirm_pause_ms or 0))
        self.highlight_ms = max(0, int(highlight_ms or 0))

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
        return await find_and_click(
            cdp,
            selector=self.selector,
            label_selector=self.label_selector,
            match_text=self.match_text,
            match_mode=MATCH_CONTAINS,
            click_enabled=self.click_enabled,
            click_selector=self.click_selector,
            highlight_enabled=self.highlight_enabled,
            confirm_pause_ms=self.confirm_pause_ms,
            highlight_ms=self.highlight_ms,
            label=self._label(),
            engine=engine,
        )

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["custom_name"] = {"type": "text", "default": "",
                            "label": "Block name (shown in stack)"}
        s["selector"] = {"type": "text", "default": "",
                         "label": "Element to find (CSS)"}
        s["label_selector"] = {"type": "text", "default": "",
                               "label": "Text element inside (CSS)"}
        s["match_text"] = {"type": "text", "default": "",
                           "label": "Text to match inside (optional — "
                                    "{{nick}} = selected user)"}
        s["click_enabled"] = {"type": "checkbox", "default": True,
                              "label": "Click after found"}
        s["click_selector"] = {"type": "text", "default": "",
                               "label": "Element inside to click (optional)"}
        s["highlight_enabled"] = {"type": "checkbox", "default": True,
                                  "label": "Draw confirmation outlines "
                                           "(red = found, orange = click)"}
        s["confirm_pause_ms"] = {"type": "number", "default": 700,
                                 "label": "Pause after found (ms)"}
        s["highlight_ms"] = {"type": "number", "default": 1200,
                             "label": "Outline duration (ms)"}
        return s
