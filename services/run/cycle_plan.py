"""Private pure cycle planner for Area C2 (no Qt/DB/CDP, no side effects).

`inspect_stack` centralises the enabled-block rules; `choose_cycle_mode`
implements the decision precedence the coordinator must follow. The
coordinator decides WHEN to inspect (pre-collect scroll lookup vs post-take
full facts) — this module is a pure function of the passed list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from .hooks import USER_SCOPED_BLOCKS
except Exception:  # pragma: no cover - import fallback for isolated use
    USER_SCOPED_BLOCKS = frozenset({
        "SCROLL_PARSE", "CONDITIONAL_SKIP", "CLICK_USER",
        "TYPE_MESSAGE", "CLICK_SEND", "ATTACH_IMAGE",
    })


@dataclass(frozen=True, slots=True)
class StackFacts:
    scroll_block: Any | None
    has_memory_click: bool
    has_take: bool
    has_conditional_skip: bool
    user_scoped_ids: tuple[str, ...]
    is_empty: bool
    enabled_count: int


@dataclass(frozen=True, slots=True)
class CycleDecision:
    mode: str
    reason: str


def _identity(block: Any) -> tuple[Any, bool]:
    """(block_id, counts) for one block; unreadable blocks report (None, False).

    `counts` is True for readable enabled blocks whatever the id type is —
    the caller counts before the string-id check so enabled_count keeps its
    "readable and enabled" meaning.
    """
    try:
        return (getattr(block, "block_id", ""),
                bool(getattr(block, "enabled", True)))
    except Exception:
        return None, False


def _memory_flag(block: Any) -> bool:
    """Memory-click flag of a CLICK_USER block; unreadable means False."""
    try:
        return bool(getattr(block, "use_person_from_memory", False))
    except Exception:
        return False


def _is_user_scoped(bid: str) -> bool:
    """User-scoped membership; unhashable ids are treated as not scoped."""
    try:
        return bid in USER_SCOPED_BLOCKS
    except Exception:
        return False


@dataclass
class _Scan:
    """Mutable single-pass accumulator; frozen into StackFacts at the end."""
    scroll: Any = None
    mem: bool = False
    take: bool = False
    skip: bool = False
    scoped: list = field(default_factory=list)


def _note_block(scan: _Scan, bid: str, block: Any) -> None:
    """Fold one enabled string-identified block into the scan."""
    if bid == "SCROLL_PARSE" and scan.scroll is None:
        scan.scroll = block
    if bid == "CLICK_USER" and _memory_flag(block):
        scan.mem = True
    if bid == "TAKE_PERSON":
        scan.take = True
    if bid == "CONDITIONAL_SKIP":
        scan.skip = True
    if _is_user_scoped(bid):
        scan.scoped.append(bid)


def inspect_stack(blocks: list | tuple | None) -> StackFacts:
    """Single-pass enabled-block rules. Never raises on odd payloads."""
    items = list(blocks or [])
    scan = _Scan()
    enabled = 0
    for block in items:
        bid, counts = _identity(block)
        if not counts:
            continue
        enabled += 1
        if not isinstance(bid, str) or not bid:
            continue
        _note_block(scan, bid, block)
    return StackFacts(
        scroll_block=scan.scroll,
        has_memory_click=scan.mem,
        has_take=scan.take,
        has_conditional_skip=scan.skip,
        user_scoped_ids=tuple(sorted(set(scan.scoped))),
        is_empty=len(items) == 0,
        enabled_count=enabled,
    )


def choose_cycle_mode(facts: StackFacts, *, has_queue: bool,
                      take_matched: bool) -> CycleDecision:
    """Decision precedence after preparation (collect/filter/order/take)."""
    if facts.has_memory_click:
        return CycleDecision(mode="single_target", reason="memory_click")
    if facts.has_take and not take_matched and not facts.user_scoped_ids and not has_queue:
        return CycleDecision(mode="empty", reason="no_take_match")
    if has_queue:
        return CycleDecision(mode="queued", reason="queue")
    if facts.is_empty:
        return CycleDecision(mode="empty_stack", reason="empty_stack")
    if facts.user_scoped_ids:
        return CycleDecision(mode="empty", reason="empty_queue")
    return CycleDecision(mode="standalone", reason="standalone")


__all__ = ["StackFacts", "CycleDecision", "inspect_stack", "choose_cycle_mode"]
