"""Generic "Find Element" action block.

This is a constructor-style block:
  * user gives the block a name (e.g. "Find Setting Button"),
  * user supplies a CSS selector (e.g. ``div[role='tab'].tab-item``)
    plus an optional child selector / text to narrow the match,
  * and optionally clicks the matched element after it is found.

The resulting config can be saved as a reusable element preset, so the same
"search + click" element can be reused later without rebuilding the block.
"""

import json
import logging
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")

# JS helper used to decide whether an element is actually clickable.
_IS_CLICKABLE_JS = """
function __isClickable(el){
    if(!el) return false;
    var r = el.getBoundingClientRect();
    if(r.width <= 0 || r.height <= 0) return false;
    if(el.disabled) return false;
    var st = window.getComputedStyle(el);
    if(st.visibility === 'hidden' || st.display === 'none') return false;
    if(st.pointerEvents === 'none') return false;
    return r.bottom > 0 && r.top < window.innerHeight;
}
"""


class FindElement(BaseAction):
    block_id = "FIND_ELEMENT"
    name = "Find Element"
    icon = "🔎"

    def __init__(self, name: str = "Find Element",
                 selector: str = "div[role='tab'].tab-item",
                 child_selector: str = "",
                 text: str = "", click: bool = True,
                 click_index: int = 0, pre_delay_ms: int = 300, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.name = name or "Find Element"
        self.selector = selector
        self.child_selector = child_selector or ""
        self.text = text or ""
        self.click = bool(click)
        self.click_index = int(click_index)

    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        await self.pre_delay()

        if not self.selector:
            self.debug(f"❌ [{self.name}] no element (rect) selector configured")
            return ActionResult.FAIL

        self.debug(f"🔍 [{self.name}] searching rect/container '{self.selector}'"
                   + (" and looking for text in '" + str(self.child_selector) + "'" if self.child_selector else "")
                   + (f" with text '{self.text}'" if self.text else ""))

        sel = json.dumps(self.selector)
        child = json.dumps(self.child_selector)
        text = json.dumps(self.text)
        click = "true" if self.click else "false"
        click_index = int(self.click_index)
        js = f"""{_IS_CLICKABLE_JS}
        (function(){{
            var sel = {sel};
            var child = {child};
            var text = {text};
            var click = {click};
            var wantIdx = {click_index};
            var els = Array.from(document.querySelectorAll(sel));
            if(!els.length) return {{found:false, count:0}};
            var matches = [];
            for(var i=0;i<els.length;i++){{
                var el = els[i];
                var textEl = child ? el.querySelector(child) : el;
                if(!textEl) continue;
                var t = (textEl.textContent || '').trim();
                if(!text || t.toLowerCase().indexOf(text.toLowerCase()) >= 0){{
                    matches.push(i);
                }}
            }}
            if(!matches.length) return {{found:false, count:0, selectorHas:els.length}};
            var idx = wantIdx < 0 ? matches.length + wantIdx : wantIdx;
            if(idx < 0 || idx >= matches.length) idx = 0;
            var target = els[matches[idx]];
            var clickable = __isClickable(target);
            var clicked = false;
            if(click && clickable){{ target.click(); clicked = true; }}
            return {{found:true, count:matches.length, index:idx,
                     clickable:clickable, clicked:clicked}};
        }})()"""

        result = await cdp.evaluate(js)
        if not isinstance(result, dict):
            result = {}

        if not result.get("found"):
            has_total = result.get("selectorHas", 0)
            if has_total:
                self.debug(f"❌ [{self.name}] search failed: "
                           f"found {has_total} element(s) but none matched the text filter")
            else:
                self.debug(f"❌ [{self.name}] search failed: no element found for '{self.selector}'")
            return ActionResult.FAIL

        count = result.get("count", 0)
        self.debug(f"✅ [{self.name}] found {count} matching element(s)")

        if not self.click:
            self.debug(f"✔ [{self.name}] found but click disabled (not clicked)")
            self.debug(f"📦 [{self.name}] step result: OK")
            return ActionResult.OK

        idx = result.get("index", 0)
        clickable = result.get("clickable", False)
        clicked = result.get("clicked", False)
        if clickable and clicked:
            self.debug(f"🖱 [{self.name}] match #{idx} is clickable → clicked")
            self.debug(f"📦 [{self.name}] step result: OK")
            return ActionResult.OK

        if clickable:
            self.debug(f"❌ [{self.name}] match #{idx} is clickable but click failed")
            return ActionResult.FAIL

        self.debug(f"❌ [{self.name}] match #{idx} found but NOT clickable")
        return ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["name"] = {"type": "text", "default": "Find Element", "label": "Block name"}
        s["selector"] = {"type": "text", "default": "div[role='tab'].tab-item",
                         "label": "CSS selector (e.g. div[role='tab'].tab-item)"}
        s["child_selector"] = {"type": "text", "default": "",
                               "label": "Child text selector (optional)"}
        s["text"] = {"type": "text", "default": "",
                     "label": "Required text (optional)"}
        s["click"] = {"type": "boolean", "default": True, "label": "Click after found"}
        s["click_index"] = {"type": "number", "default": 0,
                            "label": "Match to click (0=first, -1=last)"}
        return s
