"""Click the main room tab (e.g. 'Гостиная') to return to main chat."""

import logging
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class ClickMainTab(BaseAction):
    block_id = "CLICK_MAIN_TAB"
    name = "Click Main Tab"
    icon = "🏠"

    def __init__(self, tab_name: str = "Гостиная", pre_delay_ms: int = 500, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.tab_name = tab_name

    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        await self.pre_delay()
        esc = self.tab_name.replace("'", "\\'")
        js = f"""(function(){{
            var tabs = document.querySelectorAll('.tab-item');
            for(var i=0;i<tabs.length;i++){{
                var title = tabs[i].querySelector('.chat-title');
                if(title && title.textContent.trim().indexOf('{esc}')>=0){{
                    tabs[i].click(); return true;
                }}
            }}
            return false;
        }})()"""
        ok = await cdp.evaluate(js)
        if ok:
            log.info("Clicked main tab: %s", self.tab_name)
            return ActionResult.OK
        log.error("Main tab not found: %s", self.tab_name)
        return ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["tab_name"] = {"type": "text", "default": "Гостиная", "label": "Tab name"}
        return s
