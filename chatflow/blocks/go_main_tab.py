"""🏠 Go to Main Tab: click the room tab (default "Гостиная")."""
from __future__ import annotations

from ..browser import selectors as sel
from .base import BaseExecutor, BlockResult
from .registry import register


@register
class GoMainTab(BaseExecutor):
    action_type = "go_main_tab"
    label = "Go to Main Tab"
    icon = "🏠"
    params_schema = [{"key": "tab_title", "label": "Tab title", "type": "text",
                      "default": "Гостиная"}]

    async def execute(self, ctx, block) -> BlockResult:
        want = str(block.params.get("tab_title") or "Гостиная").strip()
        n = await ctx.ops.count(sel.TAB)
        for i in range(1, n + 1):
            title = await ctx.ops.eval_js(sel.TAB_TITLE_JS, sel.tab_title_selector(i))
            title = (title or "").strip()
            if title == want or (want and want in title):
                await ctx.ops.click(sel.tab_selector(i), timeout=5.0)
                await ctx.ops.wait(0.6)
                ctx.log(self.icon, f'Clicked main tab "{want}"')
                return BlockResult()
        return BlockResult(ok=False, error=f'tab "{want}" not found')
