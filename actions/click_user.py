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
        js = f"""(function(){{
            var items = document.querySelectorAll('user-item');
            for(var i=0;i<items.length;i++){{
                var el = items[i].querySelector('.primary-text');
                if(el && el.textContent.trim()==='{esc}'){{
                    items[i].querySelector('.user-container').click();
                    return true;
                }}
            }}
            return false;
        }})()"""
        ok = await cdp.evaluate(js)
        if ok:
            log.info("Clicked user: %s", user_nick)
            return ActionResult.OK
        log.warning("User not found in list: %s", user_nick)
        return ActionResult.FAIL
