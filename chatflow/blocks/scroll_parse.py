"""🔄 Scroll & Parse Users: scroll the virtual list, filter, feed the queue."""
from __future__ import annotations

from ..filters.engine import evaluate
from ..parse.scroll import ScrollEngine
from .base import BaseExecutor, BlockResult
from .registry import register

_SCHEMA = [
    {"key": "px", "label": "Scroll pixels/tick", "type": "number",
     "default": 300, "min": 50, "max": 3000},
    {"key": "pause", "label": "Wait per scroll (sec)", "type": "number",
     "default": 1.5, "min": 0.1, "max": 30},
    {"key": "empty_runs", "label": "Stop after empty scrolls", "type": "number",
     "default": 3, "min": 1, "max": 20},
    {"key": "max_scrolls", "label": "Max scrolls", "type": "number",
     "default": 50, "min": 1, "max": 500},
]


@register
class ScrollParse(BaseExecutor):
    action_type = "scroll_parse"
    label = "Scroll & Parse Users"
    icon = "🔄"
    params_schema = _SCHEMA

    async def execute(self, ctx, block) -> BlockResult:
        engine = ScrollEngine(ctx.ops, ctx.humanizer, ctx.s, ctx.log, ctx.rng)

        async def on_new(rows, chunk_no: int):
            passed = [r for r in rows if evaluate(r, ctx.rules)[0]]
            ctx.new_users += len(rows)
            ctx.emit("users_found", {
                "chunk": chunk_no,
                "rows": [{"nickname": r.nickname, "gender": r.gender,
                          "registered": r.registered, "is_guest": r.is_guest}
                         for r in rows],
                "passed": [r.nickname for r in passed],
            })
            for r in passed:
                if r.nickname not in ctx.queued:
                    ctx.queued.append(r.nickname)
            if passed:
                ctx.log("🎯", f"{len(passed)} passed filters — added to queue")

        summary = await engine.run(block.params, ctx.seen, on_new, ctx.stopped)
        ctx.log(self.icon,
                f"Scan done: {summary.chunks} scrolls, {summary.new_total} new users")
        return BlockResult(data={"new": summary.new_total,
                                 "queued": len(ctx.queued)})
