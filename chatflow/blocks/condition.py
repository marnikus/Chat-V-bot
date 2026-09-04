"""🚦 Condition Check: skip the next block when the expression is falsy.

Expression eval is sandboxed: no builtins, only the exposed variables
(nick, queued_count, pass_no, day, time, messages_sent) and operators.
"""
from __future__ import annotations

from datetime import datetime

from .base import BaseExecutor, BlockResult
from .registry import register


@register
class ConditionCheck(BaseExecutor):
    action_type = "condition"
    label = "Condition Check"
    icon = "🚦"
    params_schema = [{"key": "expr", "label": "Expression (falsy skips next block)",
                      "type": "text", "default": "queued_count > 0"}]

    async def execute(self, ctx, block) -> BlockResult:
        expr = str(block.params.get("expr") or "").strip()
        if not expr:
            return BlockResult()
        now = datetime.now()
        variables = {
            "nick": ctx.current_target or "",
            "queued_count": len(ctx.queued),
            "pass_no": ctx.pass_no,
            "messages_sent": ctx.messages_sent,
            "day": now.strftime("%A"),
            "time": now.strftime("%H:%M"),
        }
        try:
            value = eval(expr, {"__builtins__": {}}, variables)  # noqa: S307
        except Exception as e:
            ctx.log("⚠", f"Condition error ({expr}): {e} — treated as true")
            return BlockResult()
        if not value:
            ctx.log(self.icon, f"Condition false: {expr} — skipping next block")
            return BlockResult(data={"skip_next": True})
        return BlockResult()
