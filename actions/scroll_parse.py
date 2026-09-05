"""Scroll & Parse — the full scroll → filter → collect → queue pipeline.

This block owns the whole collection workflow (it used to be a hollow marker
whose work happened in the engine):

  STEP 1  scroll the users list, waiting for lazy-loaded people after each
          scroll and stopping only at the real end of the list;
  STEP 2  filter every newly detected person against this block's own criteria
          (which are stored as block params, so they travel with presets) and
          skip anyone already collected;
  STEP 3  order the collected list A–Z with not-yet-messaged people first, and
          finish as soon as `min_new_users` new un-messaged people are found.

The people it collects become the engine's messaging queue, which STEP 4
(`CLICK_USER`) then works through.
"""

import logging
from typing import Optional

from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.person_filter import ANY, NO, YES, PersonFilter, normalize
from backend.scroll_parser import CollectResult, ScrollParser

log = logging.getLogger("chatbot")


class ScrollParse(BaseAction):
    block_id = "SCROLL_PARSE"
    name = "Scroll & Parse Users"
    icon = "📜"

    def __init__(self, max_scrolls: int = 50, scroll_pause_ms: int = 800,
                 scroll_delta_y: int = 300,
                 viewport_selector: str =
                 "cdk-virtual-scroll-viewport.users-list-viewport",
                 load_timeout_ms: int = 2500, stall_threshold: int = 3,
                 min_new_users: int = 1,
                 person_selector: str = "user-item",
                 nick_selector: str = ".primary-text",
                 highlight_enabled: bool = True,
                 highlight_ms: int = 900,
                 confirm_pause_ms: int = 500,
                 purge_rejected: bool = True,
                 filter_female: str = YES, filter_registered: str = NO,
                 filter_guest: str = YES, filter_anonymous: str = NO,
                 use_panel_filters: bool = False,
                 pre_delay_ms: int = 300, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.max_scrolls = int(max_scrolls)
        self.scroll_pause_ms = int(scroll_pause_ms)
        self.scroll_delta_y = int(scroll_delta_y)
        self.viewport_selector = viewport_selector
        self.load_timeout_ms = int(load_timeout_ms)
        self.stall_threshold = int(stall_threshold)
        self.min_new_users = max(0, int(min_new_users))
        self.person_selector = person_selector
        self.nick_selector = nick_selector
        self.highlight_enabled = bool(highlight_enabled)
        self.highlight_ms = max(0, int(highlight_ms))
        self.confirm_pause_ms = max(0, int(confirm_pause_ms))
        # Destroy stored records for people confirmed NOT to pass the filter,
        # so a re-run can never resurrect them.
        self.purge_rejected = bool(purge_rejected)
        # Tri-state filter rules ("any" | "yes" | "no") — stored as plain block
        # params so they round-trip through the preset machinery.
        self.filter_female = normalize(filter_female, YES)
        self.filter_registered = normalize(filter_registered, NO)
        self.filter_guest = normalize(filter_guest, YES)
        self.filter_anonymous = normalize(filter_anonymous, NO)
        self.use_panel_filters = bool(use_panel_filters)
        #: last pipeline result, read by the engine to build its queue
        self.last_result: Optional[CollectResult] = None

    # ── collaborators ────────────────────────────────────────────
    def build_filter(self, panel_criteria=None) -> PersonFilter:
        return PersonFilter(
            female=self.filter_female,
            registered=self.filter_registered,
            guest=self.filter_guest,
            anonymous=self.filter_anonymous,
            panel_criteria=panel_criteria if self.use_panel_filters else None,
        )

    def build_parser(self, cdp: CDPClient, panel_criteria=None,
                     log_cb=None, on_collect=None, on_reject=None,
                     should_stop=None) -> ScrollParser:
        return ScrollParser(
            cdp=cdp,
            criteria=panel_criteria if self.use_panel_filters else None,
            viewport_sel=self.viewport_selector,
            scroll_dy=self.scroll_delta_y,
            pause_ms=self.scroll_pause_ms,
            stall_threshold=self.stall_threshold,
            max_scrolls=self.max_scrolls,
            load_timeout_ms=self.load_timeout_ms,
            person_filter=self.build_filter(panel_criteria),
            person_selector=self.person_selector,
            nick_selector=self.nick_selector,
            highlight_enabled=self.highlight_enabled,
            highlight_ms=self.highlight_ms,
            confirm_pause_ms=self.confirm_pause_ms,
            on_collect=on_collect,
            on_reject=on_reject if self.purge_rejected else None,
            should_stop=should_stop,
            log_cb=log_cb,
        )

    # ── the pipeline ─────────────────────────────────────────────
    async def run_pipeline(self, cdp: CDPClient, engine: Optional[object] = None,
                           panel_criteria=None,
                           known_messaged: set | None = None,
                           on_collect=None, on_reject=None,
                           should_stop=None) -> CollectResult:
        """Run scroll → filter → collect and return the ordered people."""
        def say(message: str, level: str = "info") -> None:
            if engine is not None:
                engine.report(message, level)

        say(f"📜 STEP 1 — scrolling '{self.viewport_selector}' "
            f"(max {self.max_scrolls} scrolls, {self.scroll_pause_ms} ms pause)",
            "info")
        # Prefer the engine's own hooks so the user table stays in sync live.
        if engine is not None:
            if on_collect is None:
                on_collect = getattr(engine, "person_collected", None)
            if on_reject is None:
                on_reject = getattr(engine, "person_rejected", None)
            if should_stop is None:
                should_stop = getattr(engine, "is_stopping", None)
        parser = self.build_parser(cdp, panel_criteria, log_cb=say,
                                   on_collect=on_collect, on_reject=on_reject,
                                   should_stop=should_stop)
        result = await parser.collect(min_new_users=self.min_new_users,
                                      known_messaged=known_messaged or set())
        self.last_result = result

        if result.collected:
            preview = ", ".join(
                f"{p.nick}{'' if not p.messaged else ' (messaged)'}"
                for p in result.collected[:8])
            more = "" if len(result.collected) <= 8 \
                else f" …+{len(result.collected) - 8} more"
            say(f"📋 STEP 3 — queue ordered (un-messaged first, then A–Z): "
                f"{preview}{more}", "success")
        return result

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        panel = getattr(engine, "criteria", None) if engine else None
        result = await self.run_pipeline(cdp, engine, panel_criteria=panel)
        if not result.collected:
            if engine:
                engine.report("⚠ No person matched the filter criteria", "warn")
            return ActionResult.FAIL
        return ActionResult.OK

    # ── UI schema ────────────────────────────────────────────────
    def config_schema(self) -> dict:
        s = super().config_schema()
        s["max_scrolls"] = {"type": "number", "default": 50,
                            "label": "Max scrolls (safety cap)"}
        s["scroll_pause_ms"] = {"type": "number", "default": 800,
                                "label": "Pause after each scroll (ms)"}
        s["scroll_delta_y"] = {"type": "number", "default": 300,
                               "label": "Scroll step (px)"}
        s["viewport_selector"] = {
            "type": "text",
            "default": "cdk-virtual-scroll-viewport.users-list-viewport",
            "label": "Scroll viewport (CSS)"}
        s["load_timeout_ms"] = {"type": "number", "default": 2500,
                                "label": "Max wait for lazy load (ms)"}
        s["stall_threshold"] = {"type": "number", "default": 3,
                                "label": "Scrolls with no new people = end"}
        s["min_new_users"] = {"type": "number", "default": 1,
                              "label": "Finish after N new un-messaged (0 = all)"}
        s["person_selector"] = {"type": "text", "default": "user-item",
                                "label": "Person row selector (CSS)"}
        s["nick_selector"] = {"type": "text", "default": ".primary-text",
                              "label": "Nickname element inside (CSS)"}
        s["highlight_enabled"] = {"type": "checkbox", "default": True,
                                  "label": "Highlight each detected person"}
        s["highlight_ms"] = {"type": "number", "default": 900,
                             "label": "Highlight duration (ms)"}
        s["confirm_pause_ms"] = {"type": "number", "default": 500,
                                 "label": "Pause after detecting a person (ms)"}
        s["purge_rejected"] = {"type": "checkbox", "default": True,
                               "label": "Remove people that fail the filter"}
        choices = [ANY, YES, NO]
        s["filter_female"] = {"type": "select", "options": choices,
                              "default": YES, "label": "Female"}
        s["filter_registered"] = {"type": "select", "options": choices,
                                  "default": NO, "label": "Registered"}
        s["filter_guest"] = {"type": "select", "options": choices,
                             "default": YES, "label": "Guest"}
        s["filter_anonymous"] = {"type": "select", "options": choices,
                                 "default": NO, "label": "Anonymous"}
        s["use_panel_filters"] = {"type": "checkbox", "default": False,
                                  "label": "Also apply Filter panel criteria"}
        return s
