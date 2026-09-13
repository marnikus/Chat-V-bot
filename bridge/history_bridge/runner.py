"""The guarded async runner every archive slot answers through.

`RunnerMixin` owns the three things that make a @Slot safe over an async
database: schedule the coroutine (or close it when no loop is running),
turn any exception into ONE `history_error` instead of a lost task, and
coerce the JS argument into a dict. It owns no state and never imports
`bridge.py` — the facade composes it.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger("chatbot")


class RunnerMixin:
    # ── guarded async runner ─────────────────────────────────────
    def _run_async(self, scope: str, coro) -> None:
        async def guarded():
            try:
                await coro
            except Exception as exc:                     # noqa: BLE001
                log.warning("archive %s failed: %s", scope, exc)
                self.history_error.emit(scope, str(exc))
        self._schedule(guarded())

    @staticmethod
    def _schedule(coro) -> bool:
        try:
            import asyncio
            asyncio.ensure_future(coro)
            return True
        except RuntimeError:
            coro.close()
            return False

    @staticmethod
    def _json_arg(raw, default=None):
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return dict(default or {})
        return data if isinstance(data, dict) else dict(default or {})

    def _need_archive(self, scope: str, req_id: str = "") -> bool:
        if self.ctx.archive is None:
            self.history_error.emit(scope, "the message archive is not "
                                            "running")
            return False
        return True
