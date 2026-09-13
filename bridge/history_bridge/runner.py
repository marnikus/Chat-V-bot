"""The guarded async runner every archive slot answers through.

`RunnerMixin` owns the three things that make a @Slot safe over an async
database: schedule the coroutine (or close it when no loop is running),
turn any exception into ONE `history_error` instead of a lost task, and
coerce the JS argument into a dict. It owns no state and never imports
`bridge.py` — the facade composes it.

The guard itself lives in `services/world_events.py::run_when_world_open`
(boot fix, 2026-09-13): the page is built BEFORE `ApplicationLifecycle
.startup` opens the world, so the first `userdb_page` of a session used to
die with "history database is not open" — delivered through `history_error`
only, so no `userdb_page_ready` ever followed and the person list stayed
empty until ↻ was pressed. Waiting there, and still reporting a failure
through `history_error`, keeps this mixin four lines long instead of growing
the class it belongs to.
"""

from __future__ import annotations

import json

from services.world_events import run_when_world_open


class RunnerMixin:
    # ── guarded async runner ─────────────────────────────────────
    def _run_async(self, scope: str, coro) -> None:
        self._schedule(run_when_world_open(
            scope, coro, getattr(self.ctx.archive, "db", None),
            self.history_error.emit))

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
