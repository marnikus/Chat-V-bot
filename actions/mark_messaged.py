"""Mark Person as Messaged — flip the {{nick}} person to Status Done.

Memory-driven, single person per run — NOT the queue: the block marks the
nick saved in this run's {{nick}} memory (Pick Person / an earlier Click
User) in the People list. It never looks at the queued users, and it marks
only when the person actually exists in the People list.

  * no nick saved this run  → ❌ fail loudly (nothing marked blindly);
  * nick not in the list    → ❌ fail ("if exist in memory");
  * already messaged        → OK, informational (idempotent);
  * marked now              → ✅ plus the live grid row update the engine
                              uses for its automatic marking.
"""

import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")


class MarkMessaged(BaseAction):
    block_id = "MARK_MESSAGED"
    name = "Mark Person as Messaged"
    icon = "✅"

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        if engine is None:
            log.warning("Mark Messaged: no engine — cannot mark anything")
            return ActionResult.FAIL

        nick = getattr(engine, "selected_nick", "") or ""
        if not nick:
            if hasattr(engine, "report"):
                engine.report(
                    "❌ Mark Person as Messaged: no person is saved in "
                    "memory this run — add a Pick Person block before it "
                    "(or let an earlier Click User click someone) so "
                    "{{nick}} has a value", "error")
            log.warning("Mark Messaged: no selected nick to mark")
            return ActionResult.FAIL

        mark = getattr(engine, "mark_person_messaged", None)
        if mark is None:
            if hasattr(engine, "report"):
                engine.report(
                    "❌ Mark Person as Messaged: the run engine does not "
                    "support marking", "error")
            return ActionResult.FAIL

        try:
            status = await mark(nick)
        except Exception as exc:
            log.warning("Mark Messaged raised: %s", exc)
            if hasattr(engine, "report"):
                engine.report(
                    f"❌ Mark Person as Messaged raised: {exc}", "error")
            return ActionResult.FAIL

        if status == "ok":
            if hasattr(engine, "report"):
                engine.report(
                    f"✅ Marked “{nick}” as messaged — Status → Done",
                    "success")
            log.info("Marked %s as messaged", nick)
            return ActionResult.OK
        if status == "already":
            if hasattr(engine, "report"):
                engine.report(
                    f"ℹ “{nick}” was already messaged — nothing to change",
                    "success")
            return ActionResult.OK
        if status == "missing":
            if hasattr(engine, "report"):
                engine.report(
                    f"❌ “{nick}” is not in the People list — nothing "
                    "marked", "error")
            return ActionResult.FAIL
        if hasattr(engine, "report"):
            engine.report(
                f"❌ Could not read the People list — “{nick}” not marked",
                "error")
        return ActionResult.FAIL
