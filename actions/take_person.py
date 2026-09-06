"""Pick Person — pick a saved person and remember its nick for {{nick}}.

A driver-style block (like Repeat Loop / Conditional Skip): it performs no
per-user action and never clicks anything. Once per run cycle the engine
asks it to choose one person from the People list by the configured rule
and remembers the nick (engine.note_selected) — every later block field
that contains {{nick}} resolves to it.

Rules (radio buttons in the UI):
  * random_new   — any RANDOM person with Status New (un-messaged);
  * random_done  — any RANDOM person with Status Done (already messaged);
  * order_first  — exactly the person with Order (#) = 1 (the first person
                   the run would process; queue_order()[0]).

When the chosen rule has no matching person, choose() returns None and the
engine warns + skips, leaving any previous selection untouched.
"""

import logging
import random
from typing import Optional

from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")

#: Human phrases used in logs/summary for each rule.
PICK_MODE_PHRASES = {
    "random_new": "any random un-messaged person (Status New)",
    "random_done": "any random already-messaged person (Status Done)",
    "order_first": "the first person in Order (#) — exactly #1",
}


class TakePerson(BaseAction):
    block_id = "TAKE_PERSON"
    name = "Pick Person"
    icon = "🎯"

    def __init__(self, pick_mode: str = "random_new", **kw):
        kw.pop("pre_delay_ms", None)  # driver block: delay is always 0
        super().__init__(pre_delay_ms=0, **kw)
        if pick_mode not in PICK_MODE_PHRASES:
            pick_mode = "random_new"
        self.pick_mode = pick_mode

    @property
    def mode_phrase(self) -> str:
        """Human phrase for the current rule (used in log warnings)."""
        return PICK_MODE_PHRASES.get(self.pick_mode, "")

    def choose(self, rows: list, engine: Optional[object] = None) -> Optional[str]:
        """Return the nick of the person this block picks (or None).

        :param rows: full People list (UserRecord rows) — already fetched by
            the engine once per cycle.
        :param engine: the running ActionEngine (used for the Order (#)
            order via queue_order).
        """
        new = [u for u in rows if not getattr(u, "messaged", False)]
        done = [u for u in rows if getattr(u, "messaged", False)]
        if self.pick_mode == "random_done":
            pool = done
        elif self.pick_mode == "order_first":
            if not new:
                return None
            if engine is not None and hasattr(engine, "queue_order"):
                ordered = engine.queue_order(rows)
                if ordered:
                    return ordered[0]
            return new[0].nick
        else:  # random_new
            pool = new
        return random.choice(pool).nick if pool else None

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        # Never reached per-user: the engine handles TAKE_PERSON at cycle
        # level. Guard anyway (e.g. standalone direct calls in tests).
        if engine:
            engine.report("🎯 Pick Person marker — handled by the engine",
                          "info")
        return ActionResult.SKIP

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["pick_mode"] = {"type": "select", "default": "random_new",
                          "options": list(PICK_MODE_PHRASES.keys()),
                          "label": "Pick which person to remember"}
        return s
