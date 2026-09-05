"""STEP 4 — Click on Person: open their chat in a new tab.

Locates the person's row in the users list by an EXACT nickname match (so
"Anna" never selects "Annabelle"), clicks it through the shared visual
confirmation runner — RED outline on the detected element, pause, ORANGE
outline on the click target, then the click — and finally confirms that a new
chat tab actually appeared before reporting the step as done.
"""

import json
import logging
from typing import Optional

from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.visual_click import find_and_click_exact

log = logging.getLogger("chatbot")


def build_tab_count_js(tab_selector: str, title_selector: str) -> str:
    """JS returning the open chat tabs and their titles."""
    return """(function(){
  try {
    var tabs = document.querySelectorAll(%(tab)s);
    var titles = [];
    for (var i = 0; i < tabs.length; i++) {
      var t = tabs[i].querySelector(%(title)s);
      titles.push(((t ? t.textContent : tabs[i].textContent) || '')
                  .trim().replace(/\\s+/g, ' '));
    }
    return JSON.stringify({count: tabs.length, titles: titles});
  } catch (err) {
    return JSON.stringify({count: 0, titles: [], error: String(err)});
  }
})()""" % {"tab": json.dumps(tab_selector), "title": json.dumps(title_selector)}


class ClickUser(BaseAction):
    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, selector: str = "user-item",
                 label_selector: str = ".primary-text",
                 click_selector: str = ".user-container",
                 tab_selector: str = "div[role='tab'].tab-item",
                 tab_title_selector: str = "p.chat-title",
                 verify_new_tab: bool = True, tab_pause_ms: int = 800,
                 highlight_enabled: bool = True, confirm_pause_ms: int = 700,
                 respect_order: bool = False,
                 pre_delay_ms: int = 1000, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.selector = selector
        self.label_selector = label_selector
        self.click_selector = click_selector
        self.tab_selector = tab_selector
        self.tab_title_selector = tab_title_selector
        self.verify_new_tab = bool(verify_new_tab)
        self.tab_pause_ms = max(0, int(tab_pause_ms))
        self.highlight_enabled = bool(highlight_enabled)
        self.confirm_pause_ms = max(0, int(confirm_pause_ms))
        # When ON, the engine works the Status-New people in the Order (#)
        # column sequence (1 first, then 2 … N) instead of the order the
        # page happened to show this run.
        self.respect_order = bool(respect_order)

    async def _read_tabs(self, cdp: CDPClient) -> Optional[dict]:
        try:
            raw = await cdp.evaluate(
                build_tab_count_js(self.tab_selector, self.tab_title_selector))
        except Exception as exc:
            log.warning("Tab count probe failed: %s", exc)
            return None
        try:
            res = json.loads(raw) if raw else None
        except (json.JSONDecodeError, TypeError):
            return None
        return res if isinstance(res, dict) else None

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        import asyncio

        await self.pre_delay()
        label = f"person “{user_nick}”"

        # Snapshot the tabs BEFORE clicking, so "a new tab appeared" is provable.
        before = await self._read_tabs(cdp) if self.verify_new_tab else None
        if before is not None and engine:
            engine.report(f"🗂 {before.get('count', 0)} chat tab(s) open before "
                          "the click", "info")

        # Find (red) → pause → click target (orange) → click, via the shared runner.
        outcome = await find_and_click_exact(
            cdp,
            text=user_nick,
            selector=self.selector,
            label_selector=self.label_selector,
            click_selector=self.click_selector,
            highlight_enabled=self.highlight_enabled,
            confirm_pause_ms=self.confirm_pause_ms,
            label=label,
            engine=engine,
        )
        if outcome != ActionResult.OK:
            return outcome

        if not self.verify_new_tab:
            return ActionResult.OK

        # Small pause so the tab has time to be created, then confirm it exists.
        if self.tab_pause_ms:
            if engine:
                engine.report(f"⏸ Waiting {self.tab_pause_ms} ms for the new tab…",
                              "info")
            await asyncio.sleep(self.tab_pause_ms / 1000.0)

        after = await self._read_tabs(cdp)
        if after is None:
            if engine:
                engine.report("⚠ Could not read the tab list to confirm the new "
                              "tab — assuming the click worked", "warn")
            return ActionResult.OK

        before_count = int((before or {}).get("count", 0) or 0)
        after_count = int(after.get("count", 0) or 0)
        titles = [str(t) for t in (after.get("titles") or [])]
        matched = any(user_nick and user_nick in t for t in titles)

        if after_count > before_count or matched:
            how = (f"tab count {before_count} → {after_count}" if
                   after_count > before_count else
                   f"a tab titled “{user_nick}” is open")
            if engine:
                engine.report(f"✅ New tab confirmed for {label} ({how})", "success")
            log.info("Opened chat tab for %s", user_nick)
            return ActionResult.OK

        if engine:
            engine.report(
                f"❌ No new tab appeared for {label} — still {after_count} tab(s): "
                + (", ".join(f"“{t[:24]}”" for t in titles[:5]) or "none"),
                "error")
        log.warning("No new tab after clicking %s", user_nick)
        return ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["selector"] = {"type": "text", "default": "user-item",
                         "label": "Person row selector (CSS)"}
        s["label_selector"] = {"type": "text", "default": ".primary-text",
                               "label": "Nickname element inside (CSS)"}
        s["click_selector"] = {"type": "text", "default": ".user-container",
                               "label": "Element to click inside (CSS)"}
        s["tab_selector"] = {"type": "text",
                             "default": "div[role='tab'].tab-item",
                             "label": "Chat tab selector (for verification)"}
        s["tab_title_selector"] = {"type": "text", "default": "p.chat-title",
                                   "label": "Tab title element (CSS)"}
        s["verify_new_tab"] = {"type": "checkbox", "default": True,
                               "label": "Confirm a new tab opened"}
        s["tab_pause_ms"] = {"type": "number", "default": 800,
                             "label": "Pause after click, before check (ms)"}
        s["highlight_enabled"] = {"type": "checkbox", "default": True,
                                  "label": "Draw confirmation outlines"}
        s["confirm_pause_ms"] = {"type": "number", "default": 700,
                                 "label": "Pause after found (ms)"}
        s["respect_order"] = {"type": "checkbox", "default": False,
                              "label": "Respect the Order (#) column — "
                                       "message people 1, 2, 3… N in list order"}
        return s
