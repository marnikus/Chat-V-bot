"""`ScrollParser` — the facade over the five scroll-parse phases.

The class owns construction, configuration and the callback/stop seams the
phases read. The phases themselves live one responsibility per mixin
(`probe`, `judge`, `loop`, `pipeline`, `notify`); the facade composes them so
the public surface other areas import stays a single class.

    collect(progress_cb, min_new_users, known_messaged, seek_nicks)  [pipeline]
      ├─ _open()                filter, _Pass, warnings              [pipeline]
      ├─ _first_snapshot()      the opening probe                    [pipeline]
      ├─ _scroll_loop()         iterate until target / end           [loop]
      │    ├─ _consume_batch()  count + seek / judge each person     [judge]
      │    └─ _scroll_and_settle()  wheel → _settle() until loaded   [loop/probe]
      └─ _finish()              sort, summarise, report              [pipeline]

Layout (leaves first, the facade imports the mixins and nothing imports it):

    constants → (result, options, runstate)
        ├─→ probe → (judge, loop) ─┬─→ pipeline → parser → __init__
        └─→ notify ────────────────┘
"""

import dataclasses

from backend.cdp_client import CDPClient
from backend.person_filter import PersonFilter

from .judge import JudgeMixin
from .loop import LoopMixin
from .notify import NotifyMixin
from .options import ScrollOptions
from .pipeline import PipelineMixin
from .probe import ProbeMixin


class ScrollParser(ProbeMixin, JudgeMixin, LoopMixin, PipelineMixin,
                   NotifyMixin):
    """Scroll through the virtual user list, filtering and collecting people."""

    def __init__(self, cdp: CDPClient, criteria=None,
                 viewport_sel: str = "cdk-virtual-scroll-viewport.users-list-viewport",
                 scroll_dy: int = 300, pause_ms: int = 800,
                 stall_threshold: int = 3, max_scrolls: int = 50,
                 load_timeout_ms: int = 2500, poll_ms: int = 150,
                 person_filter: PersonFilter | None = None,
                 person_selector: str = "user-item",
                 nick_selector: str = ".primary-text",
                 highlight_enabled: bool = True,
                 highlight_ms: int = 900,
                 confirm_pause_ms: int = 500,
                 on_collect=None,
                 on_reject=None,
                 should_stop=None,
                 log_cb=None):
        self.options = ScrollOptions(
            viewport_sel=viewport_sel, scroll_dy=scroll_dy, pause_ms=pause_ms,
            stall_threshold=stall_threshold, max_scrolls=max_scrolls,
            load_timeout_ms=load_timeout_ms, poll_ms=poll_ms,
            person_filter=person_filter, person_selector=person_selector,
            nick_selector=nick_selector, highlight_enabled=highlight_enabled,
            highlight_ms=highlight_ms, confirm_pause_ms=confirm_pause_ms,
            on_collect=on_collect, on_reject=on_reject,
            should_stop=should_stop, log_cb=log_cb)
        self._cdp = cdp
        self._criteria = criteria
        self._filter = person_filter
        self._log_cb = log_cb                  # reassignable: set_log_cb()
        self.known_nicks: set[str] = set()

    @classmethod
    def from_options(cls, cdp: CDPClient, options: ScrollOptions,
                     criteria=None) -> "ScrollParser":
        """The constructor new code should use: one config value, not 19."""
        return cls(cdp, criteria, **{
            f.name: getattr(options, f.name)
            for f in dataclasses.fields(options)})

    # ── the knobs the run reads (see `ScrollOptions`) ────────────
    @property
    def max_scrolls(self) -> int:
        return self.options.max_scrolls

    # The three callbacks stay readable and assignable on the parser: the
    # block wiring hands them over at construction (`ScrollParse.build_parser`)
    # and `tests/test_filter_purge.py` inspects them to prove a disabled purge
    # really detached the hook. Assigning writes them back into the frozen
    # options, so there is still exactly one place that holds them.
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
