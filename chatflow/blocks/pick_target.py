"""🎯 Pick Next Target: take the next queued nickname (top | random)."""
from __future__ import annotations

from .base import BaseExecutor, BlockResult
from .registry import register


@register
class PickTarget(BaseExecutor):
    action_type = "pick_target"
    label = "Pick Next Target"
    icon = "🎯"
    params_schema = [{"key": "order", "label": "Selection order", "type": "select",
                      "options": ["top", "random"], "default": "top"}]

    async def execute(self, ctx, block) -> BlockResult:
        if not ctx.queued:
            ctx.log(self.icon, "Queue empty — loop will end")
            return BlockResult(data={"terminate": True})
        if str(block.params.get("order") or "top") == "random":
            idx = ctx.rng.randrange(len(ctx.queued))
            nick = ctx.queued.pop(idx)
        else:
            nick = ctx.queued.pop(0)
        ctx.current_target = nick
        ctx.emit("target_picked", {"nickname": nick,
                                   "queued_left": len(ctx.queued)})
        ctx.log(self.icon, f'Picked target: "{nick}"')
        return BlockResult()
