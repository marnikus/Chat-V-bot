"""Virtual scroll parser: scroll → detect new persons → filter → collect.

The list is lazy-loaded through an Angular CDK virtual-scroll viewport, so a
slow response looks exactly like the end of the list. This parser therefore
distinguishes the two explicitly:

  * after each scroll it *settles* — polling until either new people appear
    (lazy load finished) or the scroll position stops changing;
  * the end of the list is only declared when the viewport is geometrically at
    the bottom AND a further settle window produced nothing new.

Every decision is reported through the log callback so the run is observable.

Family map (import direction is one-way down the list, and nothing in the
family imports this facade, so it cannot close a cycle — the F1
`db_deletion_*` pattern):

    scroll_parser_model   STOPPED, CollectResult, ScrollOptions, PassState
    scroll_parser_dom     the _EXTRACT_JS probe, ScrollDom (scroll + settle)
    scroll_parser_judge   PersonJudge (per-person decisions + callbacks)
    scroll_parser_loop    ScrollLoop (one collect() run's control flow)

This facade keeps the whole public surface — the 19-knob legacy constructor
(parity-pinned against `ScrollOptions` by
`tests/unit/backend/test_scroll_parser_options.py`), `from_options`,
`collect`, `parse`, `set_log_cb`, `known_nicks` and the three reassignable
callback properties — and re-exports the family's data types so every
existing import site is unchanged.

History: this file was 706 lines and `ScrollParser` was the largest god class
left (531 LOC / 39 methods, LCOM* 0.88, a §16.5 landmine) until the AREA D
freeze was lifted by owner ruling on 2026-09-13 and Round G step G2 split it
into this family:
docs/archive/2026-09-13-round-g-write-gate/G2_CHAT_SYNC_SCROLL_PARSER_DESIGN_2026-09-13.md
"""

from __future__ import annotations

import dataclasses
import logging

from backend.cdp_client import CDPClient
from backend.scroll_parser_dom import ScrollDom
from backend.scroll_parser_judge import PersonJudge
from backend.scroll_parser_loop import ScrollLoop
from backend.scroll_parser_model import (  # noqa: F401  (re-exported: the seam)
    STOPPED, CollectResult, PassState, ScrollOptions)

log = logging.getLogger("chatbot")

#: The seam contract — the facade plus every data type this module owned
#: before the G2 split, so `from backend.scroll_parser import …` keeps
#: working unchanged (the F1 `db_deletion.py` shim pattern; `__all__` is also
#: what tells pylint these re-exports are deliberate).
__all__ = ["STOPPED", "CollectResult", "PassState", "ScrollOptions",
           "ScrollParser"]


class ScrollParser:
    """Scroll through the virtual user list, filtering and collecting people."""

    def __init__(self, cdp: CDPClient, options: ScrollOptions | None = None,
                 criteria=None):
        # One configuration surface (Round G step 4): the 19-knob constructor
        # the G2 split kept is retired — every knob travels inside
        # `ScrollOptions`, so there is no second default list left to drift
        # and the parity test that policed it is obsolete by construction.
        self.options = options or ScrollOptions()
        self._cdp = cdp
        self._criteria = criteria
        self._filter = self.options.person_filter
        self._log_cb = self.options.log_cb     # reassignable: set_log_cb()
        self.known_nicks: set[str] = set()
        self._dom, self._judge = ScrollDom(self), PersonJudge(self)

    @classmethod
    def from_options(cls, cdp: CDPClient, options: ScrollOptions,
                     criteria=None) -> "ScrollParser":
        """G2-era alias: the constructor itself is options-first now."""
        return cls(cdp, options, criteria)

    # ── the knobs the run reads (see `ScrollOptions`) ────────────
    @property
    def max_scrolls(self) -> int:
        return self.options.max_scrolls

    # The three callbacks stay readable and assignable on the parser: the
    # block wiring hands them over at construction (`ScrollParse.build_parser`)
    # and `tests/test_filter_purge.py` inspects them to prove a disabled purge
    # really detached the hook. Assigning writes them back into the frozen
    # options, so there is still exactly one place that holds them. The
    # family's collaborators read them through this facade, live.
    @property
    def _on_collect(self):
        return self.options.on_collect

    @_on_collect.setter
    def _on_collect(self, callback) -> None:
        self.options = dataclasses.replace(self.options, on_collect=callback)

    @property
    def _on_reject(self):
        return self.options.on_reject

    @_on_reject.setter
    def _on_reject(self, callback) -> None:
        self.options = dataclasses.replace(self.options, on_reject=callback)

    @property
    def _should_stop(self):
        return self.options.should_stop

    @_should_stop.setter
    def _should_stop(self, predicate) -> None:
        self.options = dataclasses.replace(self.options,
                                           should_stop=predicate)

    # ── logging ──────────────────────────────────────────────────
    def set_log_cb(self, cb) -> None:
        """Optional (message, level) callback for debugger log lines."""
        self._log_cb = cb

    def _say(self, message: str, level: str = "info") -> None:
        if self._log_cb:
            try:
                self._log_cb(message, level)
            except Exception:
                pass
        log.log(getattr(logging, level.upper(), logging.INFO)
                if level else logging.INFO, "%s", message)

    def _stop_requested(self) -> bool:
        predicate = self._should_stop
        if predicate is None:
            return False
        try:
            return bool(predicate())
        except Exception:
            return False

    # ── the pipeline ─────────────────────────────────────────────
    async def collect(self, progress_cb=None, min_new_users: int = 0,
                      known_messaged: set | None = None,
                      seek_nicks: set | None = None) -> CollectResult:
        """Run scroll → detect → filter → collect.

        :param min_new_users: finish as soon as this many new *un-messaged*
            people have been collected (0 = always scroll to the end).
        :param known_messaged: nicks already messaged, used to mark records.
        :param seek_nicks: scroll-only mode. Instead of adding new people,
            scroll hunting for one of these already-known nicks and stop on
            the first that passes the filter. Nothing is written or purged.
        """
        loop = ScrollLoop(self)
        run = loop.open_pass(known_messaged=known_messaged, seek_nicks=seek_nicks,
                             min_new_users=min_new_users, progress_cb=progress_cb)
        if not await loop.first_snapshot(run):
            return run.result
        await loop.scroll_loop(run)
        return loop.finish(run)

    # ── backwards-compatible API ─────────────────────────────────
    async def parse(self, progress_cb=None) -> tuple[list, list]:
        """Legacy entry point: returns (all_users, filtered_users)."""
        result = await self.collect(progress_cb=progress_cb)
        return result.all_people, result.collected
