"""What one scroll pass mutates, so the phases do not need 12 arguments."""

from dataclasses import dataclass, field

from backend.person_filter import PersonFilter

from .options import ScrollOptions
from .result import CollectResult


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
