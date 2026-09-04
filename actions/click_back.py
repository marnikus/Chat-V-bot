"""Click back to the main room tab to return from private chat."""

import logging
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


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
        sel = self.selector.replace("'", "\\'")
        child = self.child_selector.replace("'", "\\'")
        name = self.tab_name.replace("'", "\\'")
        js = f"""(function(){{
            var tabs = document.querySelectorAll('{sel}');
            for(var i=0;i<tabs.length;i++){{
                var el = tabs[i].querySelector('{child}');
                if(el && el.textContent.trim().indexOf('{name}')>=0){{
                    tabs[i].click(); return true;
                }}
            }}
            return false;
        }})()"""
        ok = await cdp.evaluate(js)
        if ok:
            log.info("Returned to tab '%s'", self.tab_name)
            return ActionResult.OK
        log.error("Back tab not found: '%s'", self.tab_name)
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
