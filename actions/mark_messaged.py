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

    # ── the run console ──────────────────────────────────────────
    @staticmethod
    def _say(engine: Optional[object], message: str,
             level: str = "info") -> None:
        """Report to the run console when there is one with a `report`."""
        if engine is not None and hasattr(engine, "report"):
            engine.report(message, level)

    def _refuse(self, engine, message: str, log_line: str = "") -> str:
        """Say why nothing was marked, then fail — never quietly (RULE 4)."""
        self._say(engine, message, "error")
        if log_line:
            log.warning(log_line)
        return ActionResult.FAIL

    #: what each answer from the engine means for this step: the line shown in
    #: the run console, its level, and the block result
    _VERDICTS = {
        "ok": ("✅ Marked “{nick}” as messaged — Status → Done", "success",
               ActionResult.OK),
        "already": ("ℹ “{nick}” was already messaged — nothing to change",
                    "success", ActionResult.OK),
        "missing": ("❌ “{nick}” is not in the People list — nothing marked",
                    "error", ActionResult.FAIL),
    }
    _UNREADABLE = ("❌ Could not read the People list — “{nick}” not marked",
                   "error", ActionResult.FAIL)

    def _outcome(self, engine, nick: str, status: str) -> str:
        message, level, result = self._VERDICTS.get(status, self._UNREADABLE)
        self._say(engine, message.format(nick=nick), level)
        if status == "ok":
            log.info("Marked %s as messaged", nick)
        return result

    # ── execution ────────────────────────────────────────────────
    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        """Mark the {{nick}} person of this run as messaged.

        Four ways this step can end, and each one is named out loud: nothing
        saved in memory, an engine that cannot mark, a person missing from the
        list, or the mark landing. The status table above owns the wording.
        """
        await self.pre_delay()
        if engine is None:
            log.warning("Mark Messaged: no engine — cannot mark anything")
            return ActionResult.FAIL
        nick = getattr(engine, "selected_nick", "") or ""
        if not nick:
            return self._refuse(
                engine,
                "❌ Mark Person as Messaged: no person is saved in memory "
                "this run — add a Pick Person block before it (or let an "
                "earlier Click User click someone) so {{nick}} has a value",
                "Mark Messaged: no selected nick to mark")
        mark = getattr(engine, "mark_person_messaged", None)
        if mark is None:
            return self._refuse(engine, "❌ Mark Person as Messaged: the run "
                                        "engine does not support marking")
        try:
            status = await mark(nick)
        except Exception as exc:                        # noqa: BLE001
            log.warning("Mark Messaged raised: %s", exc)
            return self._refuse(engine,
                                f"❌ Mark Person as Messaged raised: {exc}")
        return self._outcome(engine, nick, status)
