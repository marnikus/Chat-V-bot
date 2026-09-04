"""Human-like interaction: char-by-char typing and smooth wheel (async)."""
from __future__ import annotations

import asyncio
import random

from .delays import char_delay, jittered, wheel_chunks
from .errors import StopRequested


class Humanizer:
    """Wraps an ops object (duck-typed: keyboard_type, scroll) with pacing."""

    def __init__(self, settings, rng: random.Random | None = None):
        self.s = settings
        self.rng = rng or random.Random()

    async def type_text(self, ops, selector: str, text: str, stop_check=None) -> int:
        """Type text char-by-char; returns number of chars typed."""
        typed = 0
        for ch in text:
            if stop_check and stop_check():
                raise StopRequested
            await ops.keyboard_type(ch)
            typed += 1
            await asyncio.sleep(char_delay(self.s.typing_cps, self.s.typing_var, self.rng))
        return typed

    async def wheel(self, ops, selector: str, dy: int) -> None:
        """Smooth wheel: several small deltas with micro-gaps."""
        for tick in wheel_chunks(dy, rng=self.rng):
            await ops.scroll(selector, tick)
            await asyncio.sleep(self.rng.uniform(0.03, 0.08))

    def micro_pause_due(self, counter: int) -> bool:
        every = int(getattr(self.s, "micro_pause_every", 0) or 0)
        return every > 0 and counter > 0 and counter % every == 0

    async def micro_pause(self) -> None:
        await asyncio.sleep(jittered(float(getattr(self.s, "micro_pause_sec", 0.0)),
                                     self.s.jitter, self.rng))
