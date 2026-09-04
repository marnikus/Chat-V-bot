"""Skip current user if already messaged (marker block)."""

import logging
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class ConditionalSkip(BaseAction):
    block_id = "CONDITIONAL_SKIP"
    name = "If Already Messaged → Skip"
    icon = "🔀"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0, **kw)

    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        # This is a sentinel — action_engine checks messaged status
        # and skips the user before reaching this block's execute.
        return ActionResult.SKIP
