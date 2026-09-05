"""Repeat Loop — run the whole stack several times (marker block).

A driver block, like CONDITIONAL_SKIP: it has no per-user action. The engine
reads its `repeat_count` once when a run starts and executes the full
pipeline (collect phase + per-user messaging) that many times, so one press
of Run plays the whole stack N cycles instead of exactly once.

With no Repeat Loop block (or it is disabled / count ≤ 1) the run behaves
exactly as before: one cycle.
"""

import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class RepeatLoop(BaseAction):
    block_id = "REPEAT_LOOP"
    name = "Repeat Loop"
    icon = "🔁"

    def __init__(self, repeat_count: int = 2, **kw):
        kw.pop("pre_delay_ms", None)  # marker: delay is always 0
        super().__init__(pre_delay_ms=0, **kw)
        self.repeat_count = max(1, int(repeat_count))

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        if engine:
            engine.report("🔁 Repeat Loop marker — cycle count handled by "
                          "the engine", "info")
        return ActionResult.SKIP

    def config_schema(self) -> dict:
        return {"repeat_count": {"type": "number", "default": 2,
                                 "label": "Number of loop cycles"}}
