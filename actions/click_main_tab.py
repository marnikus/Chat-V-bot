"""Click a chat room tab by configurable selector and text match."""

import logging
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class ClickMainTab(BaseAction):
    block_id = "CLICK_MAIN_TAB"
    name = "Click Main Tab"
    icon = "🏠"

    def __init__(self, selector: str = "div[role='tab'].tab-item",
                 child_selector: str = "p.chat-title",
                 tab_name: str = "Гостиная",
                 pre_delay_ms: int = 500, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.selector = selector
        self.child_selector = child_selector
        self.tab_name = tab_name

    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        await self.pre_delay()
        sel = self.selector.replace("'", "\\'")
        child = self.child_selector.replace("'", "\\'")
        name = self.tab_name.replace("'", "\\'")
        # Step1: count matching elements
        count_js = f"document.querySelectorAll('{sel}').length"
        count = await cdp.evaluate(count_js) or 0
        log.info("🔍 Selector '%s' found %d element(s)", self.selector, count)
        if count == 0:
            log.error("❌ FAIL: no elements match selector '%s'", self.selector)
            return ActionResult.FAIL
        # Step2: search for matching text and click
        js = f"""(function(){{
            var tabs = document.querySelectorAll('{sel}');
            var found = [];
            for(var i=0;i<tabs.length;i++){{
                var el = tabs[i].querySelector('{child}');
                var txt = el ? el.textContent.trim() : '(no child)';
                found.push(txt);
                if(el && txt.indexOf('{name}')>=0){{
                    tabs[i].click();
                    return {{ok:true, clicked:txt, all:found}};
                }}
            }}
            return {{ok:false, clicked:null, all:found}};
        }})()"""
        result = await cdp.evaluate(js)
        if isinstance(result, dict) and result.get("ok"):
            log.info("✅ Clicked tab '%s' (matched: '%s')", self.tab_name, result.get("clicked"))
            log.info("   Tabs scanned: %s", result.get("all", []))
            return ActionResult.OK
        all_titles = result.get("all", []) if isinstance(result, dict) else []
        log.error("❌ FAIL: tab '%s' not found among %d tab(s): %s",
                  self.tab_name, count, all_titles)
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
