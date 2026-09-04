"""Click back to the main room tab to return from private chat."""

import json
import logging
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")

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

    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        await self.pre_delay()
        sel = json.dumps(self.selector)
        child = json.dumps(self.child_selector)
        name = json.dumps(self.tab_name)
        self.debug(f"🔍 Searching Main Tab '{self.tab_name}' to return (selector '{self.selector}')")
        js = f"""{_IS_CLICKABLE_JS}
        (function(){{
            var sel = {sel};
            var child = {child};
            var name = {name};
            var tabs = Array.from(document.querySelectorAll(sel));
            var found = [];
            for(var i=0;i<tabs.length;i++){{
                var el = tabs[i];
                var textEl = child ? el.querySelector(child) : el;
                if(textEl && (textEl.textContent || '').trim().indexOf(name)>=0){{
                    found.push(el);
                }}
            }}
            if(!found.length) return {{found:false, count:tabs.length}};
            var target = found[0];
            var clickable = __isClickable(target);
            var clicked = false;
            if(clickable){{ target.click(); clicked = true; }}
            return {{found:true, count:tabs.length, matches:found.length,
                     clickable:clickable, clicked:clicked}};
        }})()"""
        result = await cdp.evaluate(js)
        if not isinstance(result, dict):
            result = {}

        if not result.get("found"):
            self.debug(f"❌ return-to-main failed: tab '{self.tab_name}' not found "
                       f"(selector saw {result.get('count', 0)} element(s), 0 matched text)")
            log.error("Back tab not found: '%s'", self.tab_name)
            return ActionResult.FAIL

        self.debug(f"✅ found main tab '{self.tab_name}' "
                   f"({result.get('matches', 1)} of {result.get('count', 0)} matched element(s))")
        if result.get("clickable") and result.get("clicked"):
            self.debug("🖱 main tab is clickable → clicked")
            log.info("Returned to tab '%s'", self.tab_name)
            return ActionResult.OK

        self.debug(f"❌ main tab was found but "
                   f"{'it is NOT clickable' if not result.get('clickable') else 'click did not succeed'}")
        log.error("Main tab '%s' found but not clickable", self.tab_name)
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
