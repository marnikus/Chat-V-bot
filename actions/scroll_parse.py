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
        # One locals() snapshot, then the table: the same names, the same
        # casts and the same attribute-insertion order as the 18 literal
        # assignments this replaces (each knob's "why" comment lives on its
        # table row now).
        values = locals()
        for name, cast in _KNOB_CASTS:
            value = values[name]
            setattr(self, name, value if cast is None else cast(value))
        #: last pipeline result, read by the engine to build its queue
        self.last_result: Optional[CollectResult] = None

    # ── collaborators ────────────────────────────────────────────
    def build_filter(self, panel_criteria=None) -> PersonFilter:
        """Build the person filter from this block's own four rules.

        :param panel_criteria: accepted for call-compatibility and IGNORED.
            The global Filter-panel criteria used to be applied on top of the
            block's rules, which meant two sources of truth for one decision.
            The four selects below are now the only ones.
        """
        return PersonFilter(
            female=self.filter_female,
            registered=self.filter_registered,
            guest=self.filter_guest,
            anonymous=self.filter_anonymous,
            panel_criteria=None,
        )

    def to_scroll_options(self, panel_criteria=None,
                          cbs: Optional[ScrollCallbacks] = None) -> ScrollOptions:
        """This block's settings, as the backend's own options value.

        A SCROLL_PARSE block IS a scroll run's configuration, so the
        translation is one expression — and anything the block does not mention
        keeps `ScrollOptions`' default instead of a copy of the numbers made
        here. `panel_criteria` is accepted and ignored, exactly as in
        `build_filter`.
        """
        cbs = cbs or ScrollCallbacks()
        return ScrollOptions(
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
            on_collect=cbs.on_collect,
            # RULE 6: only a purge that is switched on may destroy records
            on_reject=cbs.on_reject if self.purge_rejected else None,
            should_stop=cbs.should_stop,
            log_cb=cbs.log_cb,
        )

    def build_parser(self, cdp: CDPClient, panel_criteria=None,
                     cbs: Optional[ScrollCallbacks] = None) -> ScrollParser:
        return ScrollParser.from_options(
            cdp,
            self.to_scroll_options(panel_criteria=panel_criteria, cbs=cbs))

    @staticmethod
    async def _read_unmessaged(engine) -> set:
        """Nicks of people already in the list who have not been messaged.

        Fails open (empty set → normal collection) so a read problem can never
        leave the block doing nothing at all.
        """
        if engine is None:
            return set()
        reader = getattr(engine, "unmessaged_nicks", None)
        if reader is None:
            return set()
        try:
            return set(await reader())
        except Exception as exc:
            log.warning("Un-messaged read failed (collecting instead): %s", exc)
            return set()

    # ── the pipeline ─────────────────────────────────────────────
    @staticmethod
    def _say(engine: Optional[object], message: str,
             level: str = "info") -> None:
        """`engine.report` when a run is listening, silence when not."""
        if engine is not None:
            engine.report(message, level)

    @classmethod
    def _binder(cls, engine):
        """The `log_cb` shape the parser calls: (message, level)."""
        return lambda message, level="info": cls._say(engine, message, level)

    def _hooks(self, engine, on_collect, on_reject, should_stop) -> tuple:
        """Fill the three callbacks from the engine when the caller left them out.

        The engine's own hooks are what keep the user table in sync while the
        scroll runs (RULE 5), so a pipeline started from the run console must
        get them without the caller repeating the wiring.
        """
        if engine is not None:
            if on_collect is None:
                on_collect = getattr(engine, "person_collected", None)
            if on_reject is None:
                on_reject = getattr(engine, "person_rejected", None)
            if should_stop is None:
                should_stop = getattr(engine, "is_stopping", None)
        return on_collect, on_reject, should_stop

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
        run = run or PipelineRun()
        seek = await self._decide_mode(run.engine, run.seek_nicks)
        self._say(run.engine,
                  f"📜 STEP 1 — scrolling '{self.viewport_selector}' "
                  f"(max {self.max_scrolls} scrolls, "
                  f"{self.scroll_pause_ms} ms pause)", "info")
        result = await self._collect(cdp, run, seek)
        self._report_result(run.engine, result, seek)
        return result

    async def _decide_mode(self, engine, seek_nicks):
        """Scroll-only means "hunt for somebody already in the list".

        Adding nobody is the point of the mode — but with no un-messaged
        person to look for it falls through to normal collection, because the
        mode must never be a permanent off-switch for a stack that has to keep
        harvesting.
        """
        if not self.scroll_only:
            return None
        if seek_nicks is None:
            seek_nicks = await self._read_unmessaged(engine)
        if seek_nicks:
            self._say(engine, f"🔎 Scroll-only mode: {len(seek_nicks)} "
                              "un-messaged person(s) in the list — searching "
                              "the page for one of them, no new people will be "
                              "added", "warn")
            return set(seek_nicks)
        self._say(engine, "🔎 Scroll-only mode: no un-messaged people in the "
                          "list — collecting new people as usual", "info")
        return None

    async def _collect(self, cdp, run: PipelineRun, seek) -> CollectResult:
        cbs = run.cbs or ScrollCallbacks()
        on_collect, on_reject, should_stop = self._hooks(
            run.engine, cbs.on_collect, cbs.on_reject, cbs.should_stop)
        parser = self.build_parser(
            cdp, run.panel_criteria,
            ScrollCallbacks(log_cb=self._binder(run.engine),
                            on_collect=on_collect, on_reject=on_reject,
                            should_stop=should_stop))
        result = await parser.collect(min_new_users=self.min_new_users,
                                      known_messaged=run.known_messaged or set(),
                                      seek_nicks=seek)
        self.last_result = result
        return result

    def _report_result(self, engine, result: CollectResult, seek) -> None:
        """What the run console says about a finished pass."""
        if result.seeking:
            if result.found is not None:
                self._say(engine, f"⏹ Scroll-only: stopping the scroll at "
                                  f"“{result.found.nick}” — no new people were "
                                  "added", "success")
            elif not result.stopped:
                self._say(engine, f"⚠ Scroll-only: reached the end of the list, "
                                  f"none of the {len(seek or ())} un-messaged "
                                  "people are on the page", "warn")
            return
        if result.collected:
            preview = ", ".join(
                f"{p.nick}{'' if not p.messaged else ' (messaged)'}"
                for p in result.collected[:8])
            more = "" if len(result.collected) <= 8 \
                else f" …+{len(result.collected) - 8} more"
            self._say(engine, f"📋 STEP 3 — queue ordered (un-messaged first, "
                              f"then A–Z): {preview}{more}", "success")

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
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
