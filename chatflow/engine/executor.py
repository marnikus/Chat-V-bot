"""Sequence executor: pass loop, block dispatch, sub-loops, error policy."""
from __future__ import annotations

import asyncio
import time

from ..blocks import registry
from ..blocks.base import BlockResult
from ..core import events
from ..core.models import Block
from ..engine.delays import jittered
from ..engine.errors import OpError, StopRequested

# blocks whose failure means "the target was not contacted — requeue it"
_TARGET_BLOCKS = {"click_user", "type_message", "send_message", "attach_image"}

# after N consecutive failed passes on the same target, drop it from the
# queue (and flag it SKIPPED) so a broken target can't loop the run forever
MAX_TARGET_FAILURES = 3


class SequenceExecutor:
    def __init__(self, emit, log, settings):
        self.emit = emit
        self.log = log
        self.s = settings

    async def run_sequence(self, blocks: list[Block], ctx) -> dict:
        t0 = time.monotonic()
        while not ctx.stopped():
            ctx.pass_no += 1
            self.emit(events.LOG, events.log("info", f"Sequence loop #{ctx.pass_no} starting…", "▶"))
            res = await self._run_range(blocks, 0, len(blocks), ctx)
            if res.get("terminated") or ctx.stopped():
                break
        summary = events.run_summary(ctx.messages_sent, ctx.pass_no,
                                     ctx.block_errors, ctx.new_users,
                                     time.monotonic() - t0)
        self.emit(events.RUN_SUMMARY, summary)
        return summary

    async def _run_range(self, blocks: list[Block], start: int, end: int, ctx) -> dict:
        out = {"terminated": False}
        skip_next = False
        i = start
        while i < end and not ctx.stopped():
            b = blocks[i]
            i += 1
            if not b.enabled:
                continue
            if skip_next:
                skip_next = False
                self.log("⏭", f"Skipped block: {b.action_type}")
                continue
            if b.action_type == "loop":
                closing = self._closing_index(blocks, i, end)
                iters = max(1, int(b.params.get("iterations", 3) or 3))
                for _ in range(iters):
                    if ctx.stopped():
                        break
                    inner = await self._run_range(blocks, i, closing, ctx)
                    if inner.get("terminated"):
                        out["terminated"] = True  # propagate to the pass loop
                        break
                i = closing  # the closing marker itself runs in outer scope
                if out.get("terminated"):
                    break
                continue
            result, err = await self._exec_one(b, ctx)
            if err:
                ctx.block_errors += 1
            skip_next = result.skip_next
            if result.terminate:
                out["terminated"] = True
                break
            delay = max(0.0, min(float(b.delay_after or 0.0), 60.0))
            if delay:
                await asyncio.sleep(jittered(delay, self.s.jitter, ctx.rng))
        return out

    def _closing_index(self, blocks: list[Block], start: int, end: int) -> int:
        for j in range(start, end):
            if blocks[j].enabled and blocks[j].action_type == "loop":
                return j
        return end

    async def _exec_one(self, b: Block, ctx) -> tuple[BlockResult, bool]:
        executor = registry.get(b.action_type)
        if executor is None:
            self.log("⚠", f"Unknown block type: {b.action_type}")
            return BlockResult(ok=False, error="unknown block type"), True
        try:
            result = await executor.execute(ctx, b)
        except StopRequested:
            raise
        except OpError as e:
            self.log("⚠", f'Block "{b.action_type}" failed: {e}')
            self._requeue_target(ctx, b)
            return BlockResult(ok=False, error=str(e)), True
        except Exception as e:  # defensive: one block must never kill the loop
            self.log("⚠", f'Block "{b.action_type}" crashed: {e}')
            self._requeue_target(ctx, b)
            return BlockResult(ok=False, error=str(e)), True
        if not result.ok:
            self.log("⚠", f'Block "{b.action_type}": {result.error}')
            self._requeue_target(ctx, b)
            if getattr(self.s, "fail_policy", "skip_block") == "skip_iteration":
                return BlockResult(ok=False, error=result.error,
                                   data={"terminate": True}), True
        if result.ok and b.action_type == "send_message" and ctx.current_target:
            ctx.target_fail_counts.pop(ctx.current_target, None)
        return result, not result.ok

    @staticmethod
    def _requeue_target(ctx, b: Block) -> None:
        """A failed mid-target block keeps the user queued for the next pass,
        unless it has failed MAX_TARGET_FAILURES consecutive passes."""
        nick = ctx.current_target
        if b.action_type not in _TARGET_BLOCKS or not nick:
            return
        count = ctx.target_fail_counts.get(nick, 0) + 1
        ctx.target_fail_counts[nick] = count
        if count >= MAX_TARGET_FAILURES:
            if nick in ctx.queued:
                ctx.queued.remove(nick)
            ctx.current_target = None
            ctx.log("⚠", f'"{nick}" failed {count} times in a row — dropped from queue')
            ctx.emit("users_updated", {"nickname": nick, "status": "SKIPPED",
                                       "skip_reason": "automation-failed"})
            return
        if nick not in ctx.queued:
            ctx.queued.insert(0, nick)
