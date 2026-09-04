"""Click back to the main room tab to return from private chat."""

import logging
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class ClickBack(BaseAction):
    block_id = "CLICK_BACK"
    name = "Return to Main"
    icon = "🔙"

    def __init__(self, tab_name: str = "Гостиная", pre_delay_ms: int = 800, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.tab_name = tab_name

    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        await self.pre_delay()
        esc = self.tab_name.replace("'", "\\'")
        js = f"""(function(){{
            var icons = document.querySelectorAll("mat-icon[data-mat-icon-name='room']");
            for(var i=0;i<icons.length;i++){{
                var tab = icons[i].closest('.tab-item');
                if(tab){{ tab.click(); return true; }}
            }}
            return false;
        }})()"""
        ok = await cdp.evaluate(js)
        if ok:
            log.info("Returned to main tab")
            return ActionResult.OK
        log.warning("Room tab icon not found, trying title match")
        js2 = f"""(function(){{
            var tabs = document.querySelectorAll('.tab-item');
            for(var i=0;i<tabs.length++){{
                var t = tabs[i].querySelector('.chat-title');
                if(t && t.textContent.trim().indexOf('{esc}')>=0){{
                    tabs[i].click(); return true;
                }}
            }}
            return false;
        }})()"""
        ok2 = await cdp.evaluate(js2)
        return ActionResult.OK if ok2 else ActionResult.FAIL
