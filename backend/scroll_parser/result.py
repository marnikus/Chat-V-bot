"""Outcome of one full scroll-parse pipeline run."""

from dataclasses import dataclass, field


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
