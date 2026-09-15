"""Pure data of one scroll-parse run: outcome, options, per-pass state.

First file of the `scroll_parser_*` family (facade and family map:
`backend/scroll_parser.py`). Deliberately no `from __future__ import
annotations` here: the dataclass field types below are part of the AREA D
golden snapshot, and keeping them eagerly evaluated preserves their recorded
representation byte-for-byte through the Round G step G2 split.
"""

from dataclasses import dataclass, field

from backend.person_filter import PersonFilter


#: Returned by :meth:`backend.scroll_parser_dom.ScrollDom.settle` when the
#: user stopped the run before any snapshot could be taken — distinct from
#: ``None``, which means the page context was genuinely lost.
STOPPED = object()


@dataclass
class CollectResult:
    """Outcome of one full scroll-parse pipeline run."""
    all_people: list = field(default_factory=list)
    collected: list = field(default_factory=list)
    scrolls: int = 0
    reached_end: bool = False
    stopped_early: bool = False
    stopped: bool = False                            # halted by the user
    seeking: bool = False                            # scroll-only seek run
    found: object = None                             # person located by a seek
    rejected: dict = field(default_factory=dict)     # reason -> count
    rejected_people: list = field(default_factory=list)   # (record, reason)
    purged: list = field(default_factory=list)       # nicks destroyed

    @property
    def new_unmessaged(self) -> list:
        return [p for p in self.collected if not p.messaged]


#: The pipeline's pacing and appearance knobs, in one immutable place.
#:
#: `ScrollParser.__init__` used to take these as 17 keyword arguments, which
#: meant every phase of the run threaded them along by hand and
#: `actions/scroll_parse.py` had to unpack its whole block configuration into
#: them one by one. They are data now: `ScrollOptions`, and the block can hand
#: the same thing over as one value (`ScrollParser.from_options`).
@dataclass(frozen=True, slots=True)
class ScrollOptions:
    """Configuration of one scroll-parse run."""

    viewport_sel: str = "cdk-virtual-scroll-viewport.users-list-viewport"
    scroll_dy: int = 300
    #: pause after each wheel event, so the page can catch up
    pause_ms: int = 800
    #: how many quiet scrolls in a row mean "this list is done"
    stall_threshold: int = 3
    max_scrolls: int = 50
    #: how long to wait for lazy-loaded people after a scroll
    load_timeout_ms: int = 2500
    poll_ms: int = 150
    person_filter: PersonFilter | None = None
    person_selector: str = "user-item"
    nick_selector: str = ".primary-text"
    highlight_enabled: bool = True
    highlight_ms: int = 900
    #: how long a drawn confirmation stays on screen
    confirm_pause_ms: int = 500
    #: async callback invoked right after each person is collected, so the
    #: UI list can refresh immediately instead of at the end of the run
    on_collect: object = None
    #: async callback for people that FAIL the filter, so the caller can
    #: destroy any stored record for them
    on_reject: object = None
    #: predicate returning True when the user asked the run to stop
    should_stop: object = None
    #: (message, level) callback for the debugger pane
    log_cb: object = None

    def __post_init__(self):
        # the three knobs the old constructor normalised — same clamping,
        # same place (a negative highlight would make the JS timer fire
        # immediately and the user would never see the outline)
        _set = object.__setattr__
        _set(self, "highlight_enabled", bool(self.highlight_enabled))
        _set(self, "highlight_ms", max(0, int(self.highlight_ms)))
        _set(self, "confirm_pause_ms", max(0, int(self.confirm_pause_ms)))

    def seconds(self, ms_attr: str) -> float:
        return getattr(self, ms_attr) / 1000.0


@dataclass
class PassState:
    """What one scroll pass mutates, so the phases do not need 12 arguments.

    `seeking` is a snapshot of "the caller handed us names", taken BEFORE the
    loop starts shrinking `seek_nicks` — the mode must not silently flip off
    halfway through a run (RULE 9).

    Named `PassState` (was the private `_Pass`) because the Round G step G2
    split moved it across a module boundary inside the family, and an
    underscore name imported by siblings reads as a contract violation.
    """

    result: CollectResult
    person_filter: PersonFilter
    options: ScrollOptions
    seeking: bool = False
    seek_nicks: set = field(default_factory=set)
    known_messaged: set = field(default_factory=set)
    min_new_users: int = 0
    progress_cb: object = None
    #: nicks already added in THIS run (belt and braces against a page that
    #: renders the same person twice in one viewport)
    collected_nicks: set = field(default_factory=set)
    snap: dict = field(default_factory=dict)
    new_this_scroll: int = 0
    no_new_count: int = 0
