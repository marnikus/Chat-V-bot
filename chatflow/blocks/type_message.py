"""⌨️ Type Message: render template, humanized typing into the textarea."""
from __future__ import annotations

from ..browser import selectors as sel
from .base import BaseExecutor, BlockResult
from .registry import register


@register
class TypeMessage(BaseExecutor):
    action_type = "type_message"
    label = "Type Message"
    icon = "⌨️"
    params_schema = [{"key": "source", "label": "Source", "type": "select",
                      "options": ["single", "pool"], "default": "single"}]

    async def execute(self, ctx, block) -> BlockResult:
        if not ctx.current_target:
            return BlockResult(ok=False, error="no target picked")
        msg = ctx.render(ctx.pick_message(block)).strip()
        if not msg:
            ctx.log("⚠", "Message is empty — nothing typed")
            return BlockResult(data={"skipped": True})
        if len(msg) > ctx.s.msg_max_len:
            msg = msg[: ctx.s.msg_max_len]
            ctx.log("⚠", f"Message truncated to {ctx.s.msg_max_len} chars")
        await ctx.ops.eval_js(sel.CLEAR_TEXTAREA_JS, sel.TEXTAREA)
        await ctx.humanizer.type_text(ctx.ops, sel.TEXTAREA, msg, ctx.stopped)
        ctx.last_message = msg
        ctx.log(self.icon, f'Typed: "{msg}"')
        return BlockResult(data={"text": msg})
