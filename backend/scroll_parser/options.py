"""The pipeline's pacing and appearance knobs, in one immutable place.

`ScrollParser.__init__` used to take these as 17 keyword arguments, which
meant every phase of the run threaded them along by hand and
`actions/scroll_parse.py` had to unpack its whole block configuration into
them one by one. They are data now: `ScrollOptions`, and the block can hand
the same thing over as one value (`ScrollParser.from_options`).
"""

from dataclasses import dataclass

from backend.person_filter import PersonFilter


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
