"""The scroll run itself — `ScrollParse`'s builders and pipeline (G7 §4.2).

`ScrollParse` (actions/scroll_parse.py) is the RULE 3 block wire: its
`__init__` keyword list, the knob insertion order, `to_dict` and
`config_schema` are pinned byte-for-byte (tests/unit/actions/
block_wire_snapshot.json). Everything that is NOT wire — translating the
knobs into backend values and driving scroll → filter → collect → report —
lives here, reading the knobs off `self._block`.

`PipelineRun`/`ScrollCallbacks` stay defined in `actions.scroll_parse`:
they are golden-visible names (the AREA-D snapshot records their owning
module, and three delegate annotations quote their dotted path), so this
module imports them instead of owning them. The block imports
`ScrollRunPart` lazily inside `__init__` — the house cycle-breaker (same
shape as the G7 §3 `_Parts` bundle).
"""

from __future__ import annotations

import logging
from typing import Optional

from actions.scroll_parse import PipelineRun, ScrollCallbacks
from backend.cdp_client import CDPClient
from backend.person_filter import PersonFilter
from backend.scroll_parser import CollectResult, ScrollOptions, ScrollParser

log = logging.getLogger("chatbot")


class ScrollRunPart:
    """Knob translation + the pipeline, one cohesive collaborator.

    Every method reads the block's knobs through `self._block`, which is
    also the LCOM* story (G7 §4.2): the old class scored 0.92 because its
    18 wire attributes spread thinly over 14 methods; the block keeps the
    wire and this part keeps the run.
    """

    def __init__(self, block):
        self._block = block

    # ── collaborators ────────────────────────────────────────────
    def build_filter(self, panel_criteria=None) -> PersonFilter:
        """Build the person filter from the block's own four rules.

        :param panel_criteria: accepted for call-compatibility and IGNORED.
            The global Filter-panel criteria used to be applied on top of the
            block's rules, which meant two sources of truth for one decision.
            The four selects below are now the only ones.
        """
        block = self._block
        return PersonFilter(
            female=block.filter_female,
            registered=block.filter_registered,
            guest=block.filter_guest,
            anonymous=block.filter_anonymous,
            panel_criteria=None,
        )

    def to_scroll_options(self, panel_criteria=None,
                          cbs: Optional[ScrollCallbacks] = None) -> ScrollOptions:
        """The block's settings, as the backend's own options value.

        A SCROLL_PARSE block IS a scroll run's configuration, so the
        translation is one expression — and anything the block does not mention
        keeps `ScrollOptions`' default instead of a copy of the numbers made
        here. `panel_criteria` is accepted and ignored, exactly as in
        `build_filter`.
        """
        block = self._block
        cbs = cbs or ScrollCallbacks()
        return ScrollOptions(
            viewport_sel=block.viewport_selector,
            scroll_dy=block.scroll_delta_y,
            pause_ms=block.scroll_pause_ms,
            stall_threshold=block.stall_threshold,
            max_scrolls=block.max_scrolls,
            load_timeout_ms=block.load_timeout_ms,
            person_filter=self.build_filter(panel_criteria),
            person_selector=block.person_selector,
            nick_selector=block.nick_selector,
            highlight_enabled=block.highlight_enabled,
            highlight_ms=block.highlight_ms,
            confirm_pause_ms=block.confirm_pause_ms,
            on_collect=cbs.on_collect,
            # RULE 6: only a purge that is switched on may destroy records
            on_reject=cbs.on_reject if block.purge_rejected else None,
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

    async def run(self, cdp: CDPClient,
                  run: Optional[PipelineRun] = None) -> CollectResult:
        """Run scroll → filter → collect and return the ordered people.

        Three steps: decide the mode, let `ScrollParser` run the passes,
        report the queue. Each one owns its own lines in the run console,
        which is why `execute()` and a caller driving `run_pipeline()`
        directly always see the same story. (The public documentation of
        the request value lives on the block's `run_pipeline` delegate.)
        """
        block = self._block
        run = run or PipelineRun()
        seek = await self._decide_mode(run.engine, run.seek_nicks)
        self._say(run.engine,
                  f"📜 STEP 1 — scrolling '{block.viewport_selector}' "
                  f"(max {block.max_scrolls} scrolls, "
                  f"{block.scroll_pause_ms} ms pause)", "info")
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
        if not self._block.scroll_only:
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
        block = self._block
        cbs = run.cbs or ScrollCallbacks()
        on_collect, on_reject, should_stop = self._hooks(
            run.engine, cbs.on_collect, cbs.on_reject, cbs.should_stop)
        parser = self.build_parser(
            cdp, run.panel_criteria,
            ScrollCallbacks(log_cb=self._binder(run.engine),
                            on_collect=on_collect, on_reject=on_reject,
                            should_stop=should_stop))
        result = await parser.collect(
            min_new_users=block.min_new_users,
            known_messaged=run.known_messaged or set(),
            seek_nicks=seek)
        #: the engine reads `last_result` off the BLOCK to build its queue —
        #: the attribute lives there, wire-visible behaviour unchanged
        block.last_result = result
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
