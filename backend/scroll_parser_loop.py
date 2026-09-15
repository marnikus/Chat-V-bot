"""The scroll loop of one run: open, judge each viewport, advance, finish.

Part of the `scroll_parser_*` family (facade and family map:
`backend/scroll_parser.py`). Built per `collect()` call — it holds the
lifetime state of exactly one run.
"""

from __future__ import annotations

import asyncio
import logging

from backend.person_filter import PersonFilter, sort_people
from backend.scroll_parser_model import STOPPED, CollectResult, PassState

log = logging.getLogger("chatbot")


class ScrollLoop:
    """The pipeline control flow, minus the DOM and the per-person judging.

    Holds the facade and reads its `options` / `known_nicks` **live** — the
    callback setters replace the frozen options object.
    """

    def __init__(self, parser):
        self.p = parser

    # ── phase 1: the filter, the first snapshot, the warnings ────
    def open_pass(self, *, known_messaged, seek_nicks, min_new_users,
                  progress_cb) -> PassState:
        seeking = bool(seek_nicks)
        run = PassState(
            result=CollectResult(seeking=seeking),
            person_filter=self.p._filter or PersonFilter(
                female="any", registered="any", guest="any", anonymous="any",
                panel_criteria=self.p._criteria),
            options=self.p.options, seeking=seeking,
            seek_nicks=set(seek_nicks or ()),
            known_messaged=known_messaged or set(),
            min_new_users=min_new_users, progress_cb=progress_cb)
        self.p._say(f"🔍 Viewport selector: {self.p.options.viewport_sel}", "info")
        self.p._say(f"🧮 Filter: {run.person_filter.describe()}", "info")
        if seeking:
            self.p._say(f"🔎 Seeking {len(run.seek_nicks)} un-messaged person(s) "
                        "— no new people will be added", "warn")
        return run

    async def first_snapshot(self, run: PassState) -> bool:
        """The opening probe: False means the page has nothing to say."""
        snap = await self.p._dom.snapshot()
        if snap is None:
            self.p._say("❌ Element search failed: no data returned from the page "
                        "(wrong page? not connected?)", "error")
            return False
        if not snap.get("viewport"):
            self.p._say(f"⚠ Scroll viewport '{self.p.options.viewport_sel}' not "
                        "found — parsing whatever is currently rendered", "warn")
        run.snap = snap
        return True

    # ── phase 3: report, decide, scroll, settle ──────────────────
    async def scroll_loop(self, run: PassState) -> None:
        for scroll_i in range(self.p.options.max_scrolls):
            if self.p._stop_requested():
                run.result.stopped = True
                self.p._say("⏹ Stopped by user — halting the scroll", "warn")
                return
            run.result.scrolls = scroll_i + 1
            run.new_this_scroll = 0
            await self.p._judge.consume_batch(run)
            if run.result.found is not None:
                run.result.stopped_early = True
                return
            if not await self.advance(run, scroll_i):
                return
        self.p._say(f"⏹ Reached max scrolls ({self.p.options.max_scrolls})", "warn")

    async def advance(self, run: PassState, scroll_i: int) -> bool:
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
        if self.target_reached(run) or self.list_is_over(run):
            return False
        return await self.scroll_and_settle(run)

    def target_reached(self, run: PassState) -> bool:
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

    def list_is_over(self, run: PassState) -> bool:
        """End of list: only when geometrically at the bottom AND quiet.

        A slow response looks exactly like the end of a lazy-loaded list, so
        neither half is enough on its own (module docstring).
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

    async def scroll_and_settle(self, run: PassState) -> bool:
        prev_top = float((run.snap or {}).get("scrollTop", 0))
        if not await self.p._dom.do_scroll():
            return False
        if self.p.options.pause_ms > 0:
            await asyncio.sleep(self.p.options.seconds("pause_ms"))
        settled = await self.p._dom.settle(set(self.p.known_nicks), prev_top)
        if settled is STOPPED or self.p._stop_requested():
            run.result.stopped = True
            self.p._say("⏹ Stopped by user — halting the scroll", "warn")
            return False
        if settled is None:
            self.p._say("❌ Lost the page context while scrolling", "error")
            return False
        run.snap = settled
        return True

    # ── phase 4: the outcome the caller and the log get ─────────
    def finish(self, run: PassState) -> CollectResult:
        result = run.result
        result.collected = sort_people(result.collected)
        if result.rejected:
            detail = ", ".join(f"{n}× {reason}"
                               for reason, n in sorted(result.rejected.items()))
            self.p._say(f"🚫 Filtered out: {detail}", "info")
        if result.purged:
            self.p._say(f"🗑 Removed {len(result.purged)} stored record(s) for "
                        "people that do not pass the filter: "
                        + ", ".join(f"“{n}”" for n in result.purged[:8])
                        + ("…" if len(result.purged) > 8 else ""), "warn")
        self.p._say(f"📊 Parse finished: {len(result.all_people)} person(s) seen, "
                    f"{len(result.collected)} matched the filter "
                    f"({len(result.new_unmessaged)} not yet messaged)", "success")
        log.info("Collected %d/%d people", len(result.collected),
                 len(result.all_people))
        return result
