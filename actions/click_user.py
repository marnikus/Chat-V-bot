"""Click a user by nickname in the user list."""

import logging
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class ClickUser(BaseAction):
    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, pre_delay_ms: int = 1000, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)

    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        await self.pre_delay()
        esc = user_nick.replace("'", "\\'").replace("\\", "\\\\")
        # Step1: count user-item elements
        count = await cdp.evaluate("document.querySelectorAll('user-item').length") or 0
        log.info("🔍 Found %d user-item elements in list", count)
        if count == 0:
            log.error("❌ FAIL: no user-item elements on page")
            return ActionResult.FAIL
        # Step2: search and click
        js = f"""(function(){{
            var items = document.querySelectorAll('user-item');
            var names = [];
            for(var i=0;i<items.length;i++){{
                var el = items[i].querySelector('.primary-text');
                var txt = el ? el.textContent.trim() : '';
                names.push(txt);
                if(txt==='{esc}'){{
                    var container = items[i].querySelector('.user-container');
                    if(container){{ container.click(); return {{ok:true,clickable:true}}; }}
                    return {{ok:false,clickable:false}};
                }}
            }}
            return {{ok:false,names:names.slice(0,10)}};
        }})()"""
        result = await cdp.evaluate(js)
        if isinstance(result, dict) and result.get("ok"):
            log.info("✅ Clicked user: %s", user_nick)
            return ActionResult.OK
        if isinstance(result, dict) and "names" in result:
            log.error("❌ FAIL: user '%s' not found. First users: %s", user_nick, result["names"])
        else:
            log.error("❌ FAIL: user '%s' — container not clickable", user_nick)
        return ActionResult.FAIL
