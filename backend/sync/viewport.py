"""Viewport settling, fallback and restoration for conversation sync.

Imports are standard-library only. The supplied session owns shared data and
signature refresh; this phase never imports its runtime, parser, Qt or stores.
It preserves the existing await/cancellation boundaries and restoration policy.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("chatbot")


class SyncViewport:
    """Own the scroll-to-top visit and recovery of a virtualized chat pane."""

    def __init__(self, session: "SyncSession"):
        self.s = session

    async def prepare(self) -> None:
        """Backfill visits the first message, without archiving during the move."""
        s = self.s
        options = s.options
        s.before_count = int(s.state.get("count") or 0)
        if not options.backfill_older or options.stopping():
            return
        scroll = s.state.get("scroll") or {}
        s.old_top = int(scroll.get("top") or 0)
        moved = await s.parser.scroll_to_top()
        if not (moved or {}).get("ok") or options.stopping():
            return
        await self._settle_at_top()

    async def _settle_at_top(self) -> None:
        s = self.s
        await self._fetch_settled_state()
        if self._settled_ok():
            s.result.backfilled = True
            s.restored_top = s.old_top or None
            return
        s.result.backfill_pending = True
        if s.before_count > 0 and self._post_count() < s.before_count:
            await self._recover_emptied_pane()

    async def _fetch_settled_state(self) -> None:
        """Install the settled state, or re-probe on an ordinary settle failure."""
        s = self.s
        wait = max(float(s.options.backfill_wait_s or 2.0), 4.0)
        try:
            state = await s.parser.settle_after_top(
                s.state, wait_ms=300, stable_polls=3, max_wait_s=wait,
                minimum_count=s.before_count)
        except Exception:                            # noqa: BLE001
            state = await s.parser.state()
        s.state = state if isinstance(state, dict) else s.state
        s.sync_state()

    def _post_count(self) -> int:
        return int(self.s.state.get("count") or 0)

    def _settled_ok(self) -> bool:
        s = self.s
        after = s.state.get("scroll") or {}
        return (bool(after.get("atTop"))
                and bool(s.state.get("_settled"))
                and self._post_count() >= s.before_count)

    async def _recover_emptied_pane(self) -> None:
        """Restore and re-probe an emptied pane; leave its backfill pending."""
        s = self.s
        await self.restore()
        fallback = await s.parser.state()
        if int((fallback or {}).get("count") or 0) > 0:
            s.state = fallback
            s.sync_state()

    async def restore(self, position: Optional[int] = None) -> int:
        """Restore the old viewport and return the re-clamped retry window end."""
        s = self.s
        try:
            await s.parser.restore_scroll(s.old_top)
        except Exception:                            # noqa: BLE001
            pass
        state = await s.parser.state()
        count = int((state or {}).get("count") or 0)
        if count <= 0:
            return self._window_end(position)
        s.state = state
        s.count = count
        s.result.count = count
        s.sync_state()
        s.result.backfill_pending = True
        return self._window_end(position)

    def _window_end(self, position: Optional[int]) -> int:
        s = self.s
        if position is None:
            return s.position
        return min(s.count, position + int(s.parser.chunk_size))

    async def restore_if_needed(self) -> None:
        s = self.s
        if s.restored_top is None:
            return
        try:
            await s.parser.restore_scroll(s.restored_top)
        except Exception:                            # noqa: BLE001
            log.debug("could not restore scroll position for %s", s.nick)
