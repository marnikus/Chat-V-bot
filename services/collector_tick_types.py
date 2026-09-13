"""Value types passed between the phases of one collector tick.

Split out of `services/collector_tick` in round H (H3). These five carry no
behaviour and no host reference: they are what the PROBE half hands to the
ARCHIVE half. Keeping them in their own module is what lets the two halves
stay unaware of each other -- neither imports the other, both import this.

`PaneSignatures` is the reason the tick can tell "the page changed" from
"the page is the same and we already did this work": it snapshots the two
pane fingerprints so the ARCHIVE phase can compare them without re-reading
the DOM.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TickPhase(str, Enum):
    """The phases one tick walks: PROBE → GATE → NICK → VERIFY → ARCHIVE."""
    PROBE = "probe"
    GATE = "gate"
    NICK = "nick"
    VERIFY = "verify"
    ARCHIVE = "archive"
    TERMINAL = "terminal"
@dataclass(frozen=True)
class Refusal:
    """A terminal refusal: the tick ends without touching the archive."""
    state: str
    text: str
@dataclass(frozen=True)
class Outcome:
    """The terminal (state, text) a tick reports."""
    state: str
    text: str
@dataclass(frozen=True)
class Probe:
    """What the page reported this tick (after the optional self-heal)."""
    state: dict
    agent: int = 0
    self_healed: bool = False

    @property
    def count(self) -> int:
        return int(self.state.get("count") or 0)

    @property
    def partner_nick(self) -> str:
        return " ".join(str(self.state.get("partner") or "").split()).strip()

    @property
    def me_nick(self) -> str:
        return " ".join(str(self.state.get("me") or "").split()).strip()

    @property
    def out_authors(self) -> list[str]:
        return [str(o or "").strip() for o in
                (self.state.get("out_authors") or [])]
@dataclass(frozen=True, slots=True)
class PaneSignatures:
    """The four content fingerprints of one chat pane, as one value.

    `head`/`tail` are the first and last *countable* messages; `head_any`/
    `tail_any` include the ones that do not count (system lines, unrendered
    nodes). Both pairs are needed and for different jobs: the strict pair
    decides whether the cursor moved, the loose pair identifies the same
    conversation after the partner renames.

    They are computed together from one probe and travel together everywhere,
    which is why they are a value rather than four adjacent `str` parameters —
    adjacent same-typed arguments are where transpositions hide.
    """

    head: str = ""
    tail: str = ""
    head_any: str = ""
    tail_any: str = ""

    @classmethod
    def of(cls, raw: dict, signature) -> "PaneSignatures":
        """Fingerprint a probe's raw state with the caller's hash function."""
        return cls(head=signature(raw.get("head")),
                   tail=signature(raw.get("tail")),
                   head_any=signature(raw.get("head_any")),
                   tail_any=signature(raw.get("tail_any")))
