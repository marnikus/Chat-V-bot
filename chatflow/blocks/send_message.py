"""📤 Send Message: click send, verify the char counter resets, emit event.

The main thread persists MESSAGED on the `message_sent` event — this block
never touches the DB (docs §2.2 R4).
"""
from __future__ import annotations

import asyncio

from ..browser import selectors as sel
from ..core.models import now_iso
from .base import BaseExecutor, BlockResult
from .registry import register

_CONFIRM_ATTEMPTS = 10
_CONFIRM_SEC = 0.5


@register
class SendMessage(BaseExecutor):
    action_type = "send_message"
    label = "Send Message"
    icon = "📤"
    params_schema = []

    async def execute(self, ctx, block) -> BlockResult:
        if not ctx.current_target:
            return BlockResult(ok=False, error="no target picked")
        if not ctx.last_message:
            ctx.log("⚠", "Nothing was typed — skipping send")
            return BlockResult(data={"skipped": True})
        await ctx.ops.click(sel.SEND_BTN)
        if await self._confirmed(ctx):
            ctx.messages_sent += 1
            ctx.emit("message_sent", {"nickname": ctx.current_target,
                                      "text": ctx.last_message, "ts": now_iso()})
            ctx.log(self.icon, f'Message sent to "{ctx.current_target}"')
            return BlockResult()
        ctx.log("⚠", "Send not confirmed — retrying once")
        await ctx.ops.click(sel.SEND_BTN)
        if await self._confirmed(ctx):
            ctx.messages_sent += 1
            ctx.emit("message_sent", {"nickname": ctx.current_target,
                                      "text": ctx.last_message, "ts": now_iso()})
            ctx.log(self.icon, f'Message sent to "{ctx.current_target}" (retry)')
            return BlockResult()
        return BlockResult(ok=False, error="send not confirmed (counter)")

    async def _confirmed(self, ctx) -> bool:
        """Counter hint "0 / 1000" means the form was cleared = sent."""
        for _ in range(_CONFIRM_ATTEMPTS):
            await asyncio.sleep(_CONFIRM_SEC)
            text = await ctx.ops.text(sel.CHAR_COUNTER)
            if text and text.strip().startswith("0 /"):
                return True
        return False
