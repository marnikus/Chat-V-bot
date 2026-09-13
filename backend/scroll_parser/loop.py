"""The scroll loop: when to keep going, when to stop, and why.

Owns the `ScrollLoop` collaborator — pass bookkeeping, the two independent
end-of-list tests, the early-finish target, and the stop check (RULE 7: the
stop is honoured at the top of each pass *and* inside the settle poll, which
lives in `viewport.py`).

The end of the list is declared only when the viewport is geometrically at the
bottom AND a further settle produced nothing new, or when the stall counter
trips. Neither half is enough on its own — a slow lazy-load looks exactly like
the end of the list.

Host protocol: reads `host.options`, `host.known_nicks`, `host._say()`,
`host._stop_requested()`, `host.viewport` and `host.judge`.
"""

import asyncio
import logging

from backend.scroll_parser.probe import STOPPED

log = logging.getLogger("chatbot")


class ScrollLoop:
    """Pass sequencing for one scroll-parse run."""

    def __init__(self, host):
        self.p = host

    async def run(self, run) -> None:
        for scroll_i in range(self.p.options.max_scrolls):
            if self.p._stop_requested():
                run.result.stopped = True
                self.p._say("⏹ Stopped by user — halting the scroll", "warn")
                return
            run.result.scrolls = scroll_i + 1
            run.new_this_scroll = 0
            await self.p.judge.consume_batch(run)
            if run.result.found is not None:
                run.result.stopped_early = True
                return
            if not await self._advance(run, scroll_i):
                return
        self.p._say(f"⏹ Reached max scrolls ({self.p.options.max_scrolls})",
                    "warn")

    async def _advance(self, run, scroll_i: int) -> bool:
        """False = this was the last pass (and the reason was reported)."""
        if run.progress_cb:
            run.progress_cb(scroll_i + 1, len(run.result.all_people),
                            run.new_this_scroll)
        if run.new_this_scroll:
            self.p._say(f"📜 Scroll {scroll_i + 1}/{self.p.options.max_scrolls}: "
                        f"+{run.new_this_scroll} new person(s), "
                        f"{len(run.result.all_people)} seen, "
                        f"{len(run.result.collected)} collected", "info")
            run.no_new_count = 0
        else:
            run.no_new_count += 1
        if self._target_reached(run) or self._list_is_over(run):
            return False
        return await self._scroll_and_settle(run)

    def _target_reached(self, run) -> bool:
        """STEP 3 early finish: enough new un-messaged people collected."""
        if run.min_new_users <= 0:
            return False
        unmessaged = len(run.result.new_unmessaged)
        if unmessaged < run.min_new_users:
            return False
        run.result.stopped_early = True
        self.p._say(f"🎯 Collected {unmessaged} new un-messaged person(s) "
                    f"(target {run.min_new_users}) — finishing scroll early",
                    "success")
        return True

    def _list_is_over(self, run) -> bool:
        """End of list: only when geometrically at the bottom AND quiet.

        A slow response looks exactly like the end of a lazy-loaded list, so
        neither half is enough on its own (package docstring).
        """
        if (run.snap or {}).get("atBottom") and run.new_this_scroll == 0:
            run.result.reached_end = True
            self.p._say("⏹ Bottom of the list reached and no new people "
                        "loaded — end of list", "success")
            return True
        if run.no_new_count >= self.p.options.stall_threshold:
            run.result.reached_end = True
            self.p._say(f"⏹ No new people after {self.p.options.stall_threshold} "
                        "scrolls — list fully parsed (stall detected)", "warn")
            return True
        return False

    async def _scroll_and_settle(self, run) -> bool:
        prev_top = float((run.snap or {}).get("scrollTop", 0))
        if not await self.p.viewport.do_scroll():
            return False
        if self.p.options.pause_ms > 0:
            await asyncio.sleep(self.p.options.seconds("pause_ms"))
        settled = await self.p.viewport.settle(set(self.p.known_nicks),
                                               prev_top)
        if settled is STOPPED or self.p._stop_requested():
            run.result.stopped = True
            self.p._say("⏹ Stopped by user — halting the scroll", "warn")
            return False
        if settled is None:
            self.p._say("❌ Lost the page context while scrolling", "error")
            return False
        run.snap = settled
        return True
