"""👤 Click Target User: find the row (scrolling if needed), click, verify tab."""
from __future__ import annotations

import asyncio

from ..browser import selectors as sel
from .base import BaseExecutor, BlockResult
from .registry import register

_TAB_WAIT_ATTEMPTS = 10
_TAB_WAIT_SEC = 0.6


@register
class ClickUser(BaseExecutor):
    action_type = "click_user"
    label = "Click Target User"
    icon = "👤"
    params_schema = []

    async def execute(self, ctx, block) -> BlockResult:
        target = ctx.current_target
        if not target:
            return BlockResult(ok=False, error="no target picked")
        idx = await self._find_rendered(ctx, target)
        if idx is None:
            idx = await self._scroll_find(ctx, target)
        if idx is None:
            ctx.log(self.icon, f'"{target}" not visible in the list — skipped')
            return BlockResult(ok=False, error="row not found")
        await ctx.ops.click(sel.row_selector(idx))
        if await self._wait_tab(ctx, target):
            ctx.log(self.icon, f'Opened chat tab "{target}"')
            return BlockResult()
        return BlockResult(ok=False, error="chat tab did not open")

    async def _find_rendered(self, ctx, target: str):
        n = await ctx.ops.count(sel.USER_ROW)
        for i in range(1, n + 1):
            text = await ctx.ops.eval_js(sel.TEXT_JS, sel.nick_selector(i))
            if (text or "").strip() == target:
                return i
        return None

    async def _scroll_find(self, ctx, target: str):
        """The virtual list recycles rows: page down until the target renders."""
        attempts = max(2, ctx.s.max_scrolls // 3)
        for _ in range(attempts):
            if ctx.stopped():
                return None
            await ctx.ops.scroll(sel.VIEWPORT, 300)
            await asyncio.sleep(0.6)
            idx = await self._find_rendered(ctx, target)
            if idx is not None:
                return idx
        return None

    async def _wait_tab(self, ctx, target: str) -> bool:
        """Wait until a tab with exactly the target title exists; focus it.

        Exact-title check is the duplicate-nickname guard (docs §11): the tab
        the click produced must match, otherwise we abort that target.
        """
        for _ in range(_TAB_WAIT_ATTEMPTS):
            n = await ctx.ops.count(sel.TAB)
            for i in range(1, n + 1):
                title = await ctx.ops.eval_js(
                    sel.TAB_TITLE_JS, sel.tab_title_selector(i))
                if (title or "").strip() == target:
                    await ctx.ops.click(sel.tab_selector(i), timeout=4.0)
                    return True
            await asyncio.sleep(_TAB_WAIT_SEC)
        return False
