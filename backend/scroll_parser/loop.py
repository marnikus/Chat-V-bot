"""The scroll loop: when to keep going, when to stop.

`LoopMixin` owns the iteration and the two end conditions — an early target
(`_target_reached`) and the end of the list (`_list_is_over`). It does not
read the page itself; it asks `_do_scroll`/`_settle` for that and decides from
what they report.
"""

import asyncio

from .constants import STOPPED
from .runstate import _Pass


class LoopMixin:
    # ── phase 3: report, decide, scroll, settle ─────────────────
    async def _scroll_loop(self, run: _Pass) -> None:
        for scroll_i in range(self.options.max_scrolls):
            if self._stop_requested():
                run.result.stopped = True
                self._say("⏹ Stopped by user — halting the scroll", "warn")
                return
            run.result.scrolls = scroll_i + 1
            run.new_this_scroll = 0
            await self._consume_batch(run)
            if run.result.found is not None:
                run.result.stopped_early = True
                return
            if not await self._advance(run, scroll_i):
                return
        self._say(f"⏹ Reached max scrolls ({self.options.max_scrolls})", "warn")

    async def _advance(self, run: _Pass, scroll_i: int) -> bool:
        """False = this was the last pass (and the reason was reported)."""
        if run.progress_cb:
            run.progress_cb(scroll_i + 1, len(run.result.all_people),
                            run.new_this_scroll)
        if run.new_this_scroll:
            self._say(f"📜 Scroll {scroll_i + 1}/{self.options.max_scrolls}: "
                      f"+{run.new_this_scroll} new person(s), "
                      f"{len(run.result.all_people)} seen, "
                      f"{len(run.result.collected)} collected", "info")
            run.no_new_count = 0
        else:
            run.no_new_count += 1
        if self._target_reached(run) or self._list_is_over(run):
            return False
        return await self._scroll_and_settle(run)

    def _target_reached(self, run: _Pass) -> bool:
        """STEP 3 early finish: enough new un-messaged people collected."""
        if run.min_new_users <= 0:
            return False
        unmessaged = len(run.result.new_unmessaged)
        if unmessaged < run.min_new_users:
            return False
        run.result.stopped_early = True
        self._say(f"🎯 Collected {unmessaged} new un-messaged person(s) "
                  f"(target {run.min_new_users}) — finishing scroll early",
                  "success")
        return True

    def _list_is_over(self, run: _Pass) -> bool:
        """End of list: only when geometrically at the bottom AND quiet.

        A slow response looks exactly like the end of a lazy-loaded list, so
        neither half is enough on its own (module docstring).
        """
        if (run.snap or {}).get("atBottom") and run.new_this_scroll == 0:
            run.result.reached_end = True
            self._say("⏹ Bottom of the list reached and no new people "
                      "loaded — end of list", "success")
            return True
        if run.no_new_count >= self.options.stall_threshold:
            run.result.reached_end = True
            self._say(f"⏹ No new people after {self.options.stall_threshold} "
                      "scrolls — list fully parsed (stall detected)", "warn")
            return True
        return False

    async def _scroll_and_settle(self, run: _Pass) -> bool:
        prev_top = float((run.snap or {}).get("scrollTop", 0))
        if not await self._do_scroll():
            return False
        if self.options.pause_ms > 0:
            await asyncio.sleep(self.options.seconds("pause_ms"))
        settled = await self._settle(set(self.known_nicks), prev_top)
        if settled is STOPPED or self._stop_requested():
            run.result.stopped = True
            self._say("⏹ Stopped by user — halting the scroll", "warn")
            return False
        if settled is None:
            self._say("❌ Lost the page context while scrolling", "error")
            return False
        run.snap = settled
        return True
