"""Typed agent-state boundary for the private gate (Area A seam #2).

Decode JSON-compatible state into frozen values. Malformed author lists are
not evidence of a private conversation. Legacy sync/scroll callers still
consume dicts; this is not a claim that every probe has migrated.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from backend import chat_text

_AUTHOR_KEYS = ("in_authors", "out_authors", "authors")


def _text(value: Any) -> str:
    """Preserve page strings; nick normalization belongs to the gate."""
    return str(value or "")


def _count(value: Any) -> int:
    """Non-negative count; malformed/non-finite metadata cannot crash a gate."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _names(value: Any) -> tuple[str, ...]:
    """Distinct cleaned nicks in page order; a scalar is not a list."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(chat_text.distinct(value))


def _fingerprints(value: Any) -> tuple[str, ...]:
    """Preserve list order and duplicates; ignore non-list fingerprints."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(fp) for fp in value)


@dataclass(frozen=True)
class PaneAuthors:
    """Author evidence; reported=False requires a no_author_data refusal."""

    inbound: tuple[str, ...] = ()
    outbound: tuple[str, ...] = ()
    everyone: tuple[str, ...] = ()
    reported: bool = False

    @property
    def split(self) -> bool:
        """The page reported at least one author on a labeled side."""
        return bool(self.inbound or self.outbound)


@dataclass(frozen=True)
class ScrollPos:
    """Subset of pane geometry used by typed consumers."""

    at_top: bool = False
    top: int = 0


@dataclass(frozen=True)
class TabState:
    """A state summary, never the conversation contents."""

    ok: bool = False
    agent: int = 0
    reason: str = ""
    tab: str = "none"
    partner: str = ""
    title: str = ""
    me: str = ""
    participants: int = 0
    count: int = 0
    pending: int = 0
    head: tuple[str, ...] = ()
    tail: tuple[str, ...] = ()
    authors: PaneAuthors = field(default_factory=PaneAuthors)
    scroll: ScrollPos = field(default_factory=ScrollPos)

    @classmethod
    def absent(cls, reason: str = "no answer") -> "TabState":
        """No usable agent response: no private tab or author evidence."""
        return cls(reason=reason)

    def with_tab(self, tab: str, partner: str = "") -> "TabState":
        """Copy for another tab without mutating captured state."""
        return replace(self, tab=tab, partner=partner, title=partner)


def _list_like(value: Any) -> bool:
    """Null is the legacy empty-author-list representation."""
    return value is None or isinstance(value, (list, tuple))


def decode_pane_authors(data: dict) -> PaneAuthors:
    """Unreadable present lists invalidate the report rather than guessing."""
    present = [key for key in _AUTHOR_KEYS if key in data]
    if not present or not all(_list_like(data[key]) for key in present):
        return PaneAuthors()
    return PaneAuthors(inbound=_names(data.get("in_authors")),
                       outbound=_names(data.get("out_authors")),
                       everyone=_names(data.get("authors")),
                       reported=True)


def decode_scroll_pos(value: Any) -> ScrollPos:
    """Non-object geometry means not at the top."""
    if not isinstance(value, dict):
        return ScrollPos()
    return ScrollPos(at_top=bool(value.get("atTop")),
                     top=_count(value.get("top")))


def decode_tab_state(raw: Any) -> TabState:
    """Decode a dict or JSON text; unusable payloads become absent state."""
    data = chat_text.as_dict(raw)
    if not data:
        return TabState.absent()
    return TabState(ok=bool(data.get("ok", True)),
                    agent=_count(data.get("agent")),
                    reason=_text(data.get("reason")),
                    tab=_text(data.get("tab")) or "none",
                    partner=_text(data.get("partner")),
                    title=_text(data.get("title")),
                    me=_text(data.get("me")),
                    participants=_count(data.get("participants")),
                    count=_count(data.get("count")),
                    pending=_count(data.get("pending")),
                    head=_fingerprints(data.get("head")),
                    tail=_fingerprints(data.get("tail")),
                    authors=decode_pane_authors(data),
                    scroll=decode_scroll_pos(data.get("scroll")))
