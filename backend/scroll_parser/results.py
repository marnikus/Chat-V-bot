"""What one run produced, and what one pass is mutating while it runs.

Owns `CollectResult` (the outcome the caller reads) and `_Pass` (the per-pass
scratch state). Pure data: no page, no CDP, no filter logic.
"""

from dataclasses import dataclass, field

from backend.person_filter import PersonFilter
from backend.scroll_parser.options import ScrollOptions

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
    def reject_detail(self) -> str:
        """"3× not female, 1× registered" — why people were filtered out.

        Ordered by count so the dominant reason reads first: the whole point
        is to answer "why did almost nobody get added" at a glance.
        """
        pairs = sorted(self.rejected.items(), key=lambda kv: (-kv[1], kv[0]))
        return ", ".join(f"{n}× {reason}" for reason, n in pairs)

    @property
    def new_unmessaged(self) -> list:
        return [p for p in self.collected if not p.messaged]

@dataclass
class _Pass:
    """What one scroll pass mutates, so the phases do not need 12 arguments.

    `seeking` is a snapshot of "the caller handed us names", taken BEFORE the
    loop starts shrinking `seek_nicks` — the mode must not silently flip off
    halfway through a run (RULE 9).
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
