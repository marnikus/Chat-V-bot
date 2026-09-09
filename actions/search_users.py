"""Search Users — type into the users-list Поиск search box (verified).

The users list (Virt-Chat) has its own search field above the virtual
viewport: `.search-field input[matinput]`. "Поиск" is a floating mat-label
(no placeholder) and the #mat-input-N ids change on every mount, so the
block locates the field structurally and types with the same verified
chain as Type Message — PLUS it proves the field was really clicked (the
cursor is inside: document.activeElement === the field, with a real click
issued first when needed) and that the text really landed (value read-back).
"""

import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.message_injector import type_search

log = logging.getLogger("chatbot")


class SearchUsers(BaseAction):
    block_id = "SEARCH_USERS"
    name = "Search Users"
    icon = "🔍"

    def __init__(self, text: str = "", pre_delay_ms: int = 500, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.text = text

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        report = engine.report if engine else None
        ok = await type_search(cdp, self.text, report)
        return ActionResult.OK if ok else ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["text"] = {"type": "text", "default": "",
                     "label": "Search text ({{nick}} = selected user)"}
        return s
