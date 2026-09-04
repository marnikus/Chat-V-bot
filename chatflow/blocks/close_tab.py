"""🚪 Close Chat Tab: close the active person tab."""
from __future__ import annotations

from ..browser import selectors as sel
from .base import BaseExecutor, BlockResult
from .registry import register


@register
class CloseTab(BaseExecutor):
    action_type = "close_tab"
    label = "Close Chat Tab"
    icon = "🚪"
    params_schema = []

    async def execute(self, ctx, block) -> BlockResult:
        close_sel = f"{sel.TAB_ACTIVE} {sel.TAB_CLOSE}"
        if not await ctx.ops.exists(close_sel):
            ctx.log(self.icon, "No person tab to close")
            return BlockResult(data={"skipped": True})
        await ctx.ops.click(close_sel)
        await ctx.ops.wait(0.6)
        ctx.current_target = None
        ctx.log(self.icon, "Closed chat tab")
        return BlockResult()
