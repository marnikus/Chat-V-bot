"""Shared execution context handed to every block executor (worker thread)."""
from __future__ import annotations

import random
from datetime import datetime

from ..core.models import FilterRule

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday")


class BlockContext:
    def __init__(self, ops, page, settings, humanizer, queued: list,
                 emit, rng: random.Random | None = None):
        self.ops = ops
        self.page = page
        self.s = settings
        self.humanizer = humanizer
        self.queued: list[str] = list(queued or [])
        self.seen: set[str] = set()
        self.rules: list[FilterRule] = []
        self.emit = emit
        self.rng = rng or random.Random()
        self.current_target: str | None = None
        self.last_message: str = ""
        self.pass_no = 0
        self.messages_sent = 0
        self.new_users = 0
        self.block_errors = 0
        self.target_fail_counts: dict[str, int] = {}
        self._stopped = False
        self.gate = None  # async callable: awaits while paused (set by worker)

    def mark_stopped(self) -> None:
        self._stopped = True

    def stopped(self) -> bool:
        return self._stopped

    async def wait_if_stopped_or_paused(self) -> None:
        if self.stopped():
            from ..engine.errors import StopRequested
            raise StopRequested
        if self.gate is not None:
            await self.gate()

    def log(self, icon: str, msg: str) -> None:
        self.emit("log", {"level": "info", "msg": msg, "icon": icon})

    def render(self, text: str) -> str:
        """Template variables: {nick}, {time}, {day}."""
        now = datetime.now()
        return (text.replace("{nick}", self.current_target or "")
                   .replace("{time}", now.strftime("%H:%M"))
                   .replace("{day}", _WEEKDAYS[now.weekday()]))

    def pick_message(self, block) -> str:
        source = (block.params.get("source") or "single")
        if source == "pool":
            lines = [ln.strip() for ln in (self.s.message_pool or "").splitlines()
                     if ln.strip()]
            if lines:
                return self.rng.choice(lines)
        return self.s.message or ""
