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

The optional *scroll-only* mode (`scroll_only`) turns STEP 2 inside out: instead
of adding new people it scrolls hunting for someone who is ALREADY in the list
and not yet messaged, stops the scroll on the first one that passes the filter,
and writes nothing. When nobody is waiting it collects new people as usual, so
running the stack in a loop drains the backlog and then resumes harvesting.

The people it collects become the engine's messaging queue, which STEP 4
(`CLICK_USER`) then works through.

G7 §4.2 (the cohesion pass): this file is the RULE 3 block wire — the knob
table, `__init__`, the delegates, `config_schema` and the two request
dataclasses (golden-visible names), all pinned byte-for-byte by
tests/unit/actions/block_wire_snapshot.json and the AREA-D snapshot. The
run itself (knob translation + pipeline) lives in
`actions/scroll_parse_run.py` (`ScrollRunPart`), imported lazily in
`__init__`; every import source of this module is untouched.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.person_filter import ANY, NO, YES, PersonFilter, normalize
from backend.scroll_parser import CollectResult, ScrollOptions, ScrollParser

log = logging.getLogger("chatbot")


def _max0(value) -> int:
    """Clamp a stored knob to a non-negative int."""
    return max(0, int(value))


def _tri(fallback: str):
    """Caster for the tri-state filter rules ("any" | "yes" | "no")."""
    return lambda value: normalize(value, fallback)


@dataclass(frozen=True, slots=True)
class ScrollCallbacks:
    """The four hooks of one scroll run (Round G step 4).

    `to_scroll_options`/`build_parser` take this instead of threading four
    callback keywords; every field may stay None — the engine fills what the
    caller left out (`_hooks`).
    """

    log_cb: Any = None
    on_collect: Any = None
    on_reject: Any = None
    should_stop: Any = None


@dataclass(frozen=True, slots=True)
class PipelineRun:
    """One `run_pipeline` request: who drives it and over what scope.

    The fields are the old keyword parameters verbatim, in their old order;
    `None` everywhere means "normal collection, hooks from the engine".
    """

    engine: Any = None
    #: accepted for call-compatibility and ignored (see `build_filter`)
    panel_criteria: Any = None
    known_messaged: Any = None
    seek_nicks: Any = None
    cbs: Optional[ScrollCallbacks] = None


#: The 18 knob parameters of ScrollParse.__init__ are consumed BY NAME
#: through its locals() snapshot, which pylint cannot see — hence the
#: targeted unused-argument disable on the def line. The signature itself
#: is the RULE 3 wire format (old presets call it by keyword) and must not
#: change; the byte-identical block golden and the preset round-trip tests
#: pin that the table cannot silently drop or reorder a knob.
#: Every knob __init__ stores, name → caster, in the ORIGINAL assignment
#: order — the insertion order is wire-visible (to_dict/preset round-trip,
#: pinned byte-for-byte by tests/unit/actions/block_wire_snapshot.json).
#: A None caster assigns the parameter unchanged: the three selector
#: strings were never cast, and casting them would rewrite a preset's
#: null into "None".
_KNOB_CASTS = (
    ("max_scrolls", int),
    ("scroll_pause_ms", int),
    ("scroll_delta_y", int),
    ("viewport_selector", None),
    ("load_timeout_ms", int),
    ("stall_threshold", int),
    ("min_new_users", _max0),
    ("person_selector", None),
    ("nick_selector", None),
    ("highlight_enabled", bool),
    ("highlight_ms", _max0),
    ("confirm_pause_ms", _max0),
    # Destroy stored records for people confirmed NOT to pass the filter,
    # so a re-run can never resurrect them.
    ("purge_rejected", bool),
    # Scroll-only / seek mode: never add new people; instead scroll the
    # page hunting for someone already in the list who is not yet
    # messaged. Falls back to normal collection when nobody is waiting.
    ("scroll_only", bool),
    # Tri-state filter rules ("any" | "yes" | "no") — stored as plain
    # block params so they round-trip through the preset machinery.
    ("filter_female", _tri(YES)),
    ("filter_registered", _tri(NO)),
    ("filter_guest", _tri(YES)),
    ("filter_anonymous", _tri(NO)),
)

#: Retired settings. Accepted so old presets still load, then dropped so
#: they stop being written back by to_dict().
_RETIRED_KNOBS = ("use_panel_filters", "skip_if_backlog", "backlog_threshold")


class ScrollParse(BaseAction):
    block_id = "SCROLL_PARSE"
    name = "Scroll & Parse Users"
    icon = "📜"

    # Static analysis only — __init__ assigns all 18 via the _KNOB_CASTS loop.
    max_scrolls: int
    scroll_pause_ms: int
    scroll_delta_y: int
    viewport_selector: str
    load_timeout_ms: int
    stall_threshold: int
    min_new_users: int
    person_selector: str
    nick_selector: str
    highlight_enabled: bool
    highlight_ms: int
    confirm_pause_ms: int
    purge_rejected: bool
    scroll_only: bool
    filter_female: str
    filter_registered: str
    filter_guest: str
    filter_anonymous: str

    def __init__(self, max_scrolls: int = 50, scroll_pause_ms: int = 800,  # pylint: disable=unused-argument  # quality-override: params=20 reason=RULE 3 block wire: params are config_schema keys, blocks are built by cls(**data)
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
                 scroll_only: bool = False,
                 filter_female: str = YES, filter_registered: str = NO,
                 filter_guest: str = YES, filter_anonymous: str = NO,
                 pre_delay_ms: int = 300, **kw):
        for dead in _RETIRED_KNOBS:
            kw.pop(dead, None)
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        # One locals() snapshot feeds the table: same names, casts and
        # insertion order as the 18 literal assignments it replaces.
        values = locals()
        for name, cast in _KNOB_CASTS:
            value = values[name]
            setattr(self, name, value if cast is None else cast(value))
        #: last pipeline result, read by the engine to build its queue
        self.last_result: Optional[CollectResult] = None
        #: the run (G7 §4.2); lazy import (the part module imports this
        from actions.scroll_parse_run import ScrollRunPart
        self._run = ScrollRunPart(self)  #: module's dataclasses); "_" = not wire

    # ── collaborators (bodies in ScrollRunPart) ──────────────────
    def build_filter(self, panel_criteria=None) -> PersonFilter:
        """The person filter from this block's own four rules (see part)."""
        return self._run.build_filter(panel_criteria)

    def to_scroll_options(self, panel_criteria=None,
                          cbs: Optional[ScrollCallbacks] = None) -> ScrollOptions:
        """This block's settings, as the backend's own options value."""
        return self._run.to_scroll_options(panel_criteria, cbs)

    def build_parser(self, cdp: CDPClient, panel_criteria=None,
                     cbs: Optional[ScrollCallbacks] = None) -> ScrollParser:
        """`ScrollParser.from_options` over `to_scroll_options` (see part)."""
        return self._run.build_parser(cdp, panel_criteria, cbs)

    # ── the pipeline ─────────────────────────────────────────────
    async def run_pipeline(self, cdp: CDPClient,
                           run: Optional[PipelineRun] = None) -> CollectResult:
        """Run scroll → filter → collect and return the ordered people.

        Three steps: decide the mode, let `ScrollParser` run the passes, report
        the queue. Each one owns its own lines in the run console, which is why
        `execute()` and a caller driving `run_pipeline()` directly always see
        the same story.

        :param run: the request value — engine, scope and callbacks
            (`PipelineRun`); None means a plain engine-less collection.
            `run.panel_criteria` is accepted for call-compatibility and
            ignored; `run.seek_nicks` omitted are read from the engine's
            People Memory.
        """
        return await self._run.run(cdp, run)

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay(engine)
        panel = getattr(engine, "criteria", None) if engine else None
        result = await self.run_pipeline(cdp, PipelineRun(engine=engine, panel_criteria=panel))
        if result.seeking and not result.collected:
            if engine:
                engine.report("⚠ Scroll-only: no un-messaged person from the "
                              "list is currently on the page", "warn")
            return ActionResult.FAIL
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
        s["scroll_only"] = {
            "type": "checkbox", "default": False,
            "label": "Only scroll, no people adding (find existing "
                     "un-messaged person)"}
        choices = [ANY, YES, NO]
        s["filter_female"] = {"type": "select", "options": choices,
                              "default": YES, "label": "Female"}
        s["filter_registered"] = {"type": "select", "options": choices,
                                  "default": NO, "label": "Registered"}
        s["filter_guest"] = {"type": "select", "options": choices,
                             "default": YES, "label": "Guest"}
        s["filter_anonymous"] = {"type": "select", "options": choices,
                                 "default": NO, "label": "Anonymous"}
        return s
