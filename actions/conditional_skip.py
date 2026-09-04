"""Skip current user if already messaged (marker block).

This is a sentinel — the engine checks the user's messaged status during the
per-user loop and reports the skip decision there, so `execute` is never
called for it during a run.
"""

import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class ConditionalSkip(BaseAction):
    block_id = "CONDITIONAL_SKIP"
    name = "If Already Messaged → Skip"
    icon = "🔀"

    def __init__(self, **kw):
        kw.pop("pre_delay_ms", None)  # marker: delay is always 0
        super().__init__(pre_delay_ms=0, **kw)

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        if engine:
            engine.report(f"⏭ Conditional skip marker for {user_nick} — "
                          "handled by the engine", "info")
        return ActionResult.SKIP
