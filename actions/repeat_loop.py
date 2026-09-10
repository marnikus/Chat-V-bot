"""Repeat Loop — run the whole stack several times (marker block).

A driver block, like CONDITIONAL_SKIP: it has no per-user action. The engine
reads its `repeat_count` once when a run starts and executes the full pipeline
(collect phase + per-user messaging) that many times, so one press of Run plays
the whole stack N cycles instead of exactly once.

With no Repeat Loop block (or it is disabled / count ≤ 1) the run behaves
exactly as before: one cycle.
"""

from actions.base import BlockField, MarkerBlock


class RepeatLoop(MarkerBlock):
    block_id = "REPEAT_LOOP"
    name = "Repeat Loop"
    icon = "🔁"

    FIELDS = (
        BlockField("repeat_count", "number", "Number of loop cycles",
                   clean=lambda v: max(1, int(v))),
    )

    def __init__(self, repeat_count: int = 2, **kw):
        super().__init__(repeat_count=repeat_count, **kw)

    def marker_message(self, user_nick: str) -> str:
        return ("🔁 Repeat Loop marker — cycle count handled by the engine")
