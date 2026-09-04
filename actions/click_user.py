"""Click a user by nickname in the user list."""

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


class ClickUser(BaseAction):
    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, pre_delay_ms: int = 1000, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)

    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        await self.pre_delay()
        esc = json.dumps(user_nick)
        self.debug(f"🔍 Searching user '{user_nick}' in user list")
        js = f"""{_IS_CLICKABLE_JS}
        (function(){{
            var nick = {esc};
            var items = Array.from(document.querySelectorAll('user-item'));
            var match = null;
            for(var i=0;i<items.length;i++){{
                var el = items[i].querySelector('.primary-text');
                if(el && (el.textContent || '').trim()===nick){{ match = items[i]; break; }}
            }}
            if(!match) return {{found:false, count:items.length}};
            var target = match.querySelector('.user-container') || match;
            var clickable = __isClickable(target);
            var clicked = false;
            if(clickable){{ target.click(); clicked = true; }}
            return {{found:true, count:items.length, clickable:clickable, clicked:clicked}};
        }})()"""
        result = await cdp.evaluate(js)
        if not isinstance(result, dict):
            result = {}

        if not result.get("found"):
            self.debug(f"❌ search failed: user '{user_nick}' not found "
                       f"(scanned {result.get('count', 0)} user item(s))")
            log.warning("User not found in list: %s", user_nick)
            return ActionResult.FAIL

        self.debug(f"✅ found user '{user_nick}' in list")
        if result.get("clickable") and result.get("clicked"):
            self.debug("🖱 user element is clickable → clicked")
            log.info("Clicked user: %s", user_nick)
            return ActionResult.OK

        self.debug(f"❌ user '{user_nick}' found but "
                   f"{'it is NOT clickable' if not result.get('clickable') else 'click did not succeed'}")
        return ActionResult.FAIL
