"""Scroll engine: chunked wheel + render pause + empty-run stop (F-UP-*)."""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from ..browser import selectors as sel
from ..engine.delays import jittered
from ..engine.errors import StopRequested
from .extract import extract_rows


@dataclass
class ScrollSummary:
    chunks: int = 0
    new_total: int = 0
    stopped: bool = False


class ScrollEngine:
    """Scrolls the virtual list until N consecutive empty chunks (F-UP-05)."""

    def __init__(self, ops, humanizer, settings, log, rng: random.Random | None = None):
        self.ops = ops
        self.h = humanizer
        self.s = settings
        self.log = log
        self.rng = rng or random.Random()

    async def run(self, params: dict, seen: set, on_new, stop_check=None) -> ScrollSummary:
        px = _int(params.get("px"), self.s.scroll_px)
        pause = _float(params.get("pause"), self.s.scroll_pause)
        empty_limit = _int(params.get("empty_runs"), self.s.empty_runs)
        max_scrolls = _int(params.get("max_scrolls"), self.s.max_scrolls)
        summary = ScrollSummary()
        empty = 0
        for i in range(max(1, max_scrolls)):
            if stop_check and stop_check():
                summary.stopped = True
                break
            await self.h.wheel(self.ops, sel.VIEWPORT, px)
            await asyncio.sleep(jittered(pause, self.s.jitter, self.rng))
            if stop_check and stop_check():
                summary.stopped = True
                break
            rows = await extract_rows(self.ops)
            new = [r for r in rows if r.nickname not in seen]
            seen.update(r.nickname for r in rows)
            summary.chunks = i + 1
            if new:
                summary.new_total += len(new)
                self.log("🔄", f"Scrolled +{px}px — {len(new)} new users")
                await on_new(new, summary.chunks)
                empty = 0
            else:
                empty += 1
                self.log("🔄", f"Scrolled +{px}px — 0 new users ({empty}/{empty_limit})")
            if empty >= empty_limit:
                break
        return summary


def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default
