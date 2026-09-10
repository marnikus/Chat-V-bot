"""Private cycle-planning helpers (AREA C2).

Pure decisions: no Qt/DB/CDP imports, no signals, no side effects. The
coordinator keeps orchestration; this module owns the stack scan + mode table
so ``_execute_cycle`` stays small and the precedence is testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StackFacts:
    """Immutable snapshot of the enabled-block rules for one mode decision."""

    scroll_block: Any | None = None
    has_mem_click: bool = False
    has_take: bool = False
    has_conditional_skip: bool = False
    user_scoped_ids: tuple[str, ...] = ()
    stack_empty: bool = False
    all_disabled: bool = False


def _is_enabled(block) -> bool:
    return bool(getattr(block, "enabled", True))


def inspect_stack(blocks) -> StackFacts:
    """Scan ``blocks`` once and return the facts the mode table needs.

    Centralises the enabled-block rules previously repeated as five inline
    scans. ``USER_SCOPED_BLOCKS`` is imported lazily to keep this module free
    of package-level Qt edges (hooks itself imports no Qt, but the lazy edge
    documents the one-way dependency).
    """
    from .hooks import USER_SCOPED_BLOCKS

    items = list(blocks or [])
    if not items:
        return StackFacts(stack_empty=True, all_disabled=False)
    scroll_block = None
    has_mem_click = False
    has_take = False
    has_conditional_skip = False
    user_ids: set[str] = set()
    enabled_count = 0
    for block in items:
        block_id = getattr(block, "block_id", "")
        enabled = _is_enabled(block)
        if enabled:
            enabled_count += 1
        else:
            continue
        if block_id == "SCROLL_PARSE" and scroll_block is None:
            scroll_block = block
        if (
            block_id == "CLICK_USER"
            and bool(getattr(block, "use_person_from_memory", False))
        ):
            has_mem_click = True
        if block_id == "TAKE_PERSON":
            has_take = True
        if block_id == "CONDITIONAL_SKIP":
            has_conditional_skip = True
        if block_id in USER_SCOPED_BLOCKS:
            user_ids.add(block_id)
    return StackFacts(
        scroll_block=scroll_block,
        has_mem_click=has_mem_click,
        has_take=has_take,
        has_conditional_skip=has_conditional_skip,
        user_scoped_ids=tuple(sorted(user_ids)),
        stack_empty=False,
        all_disabled=(enabled_count == 0),
    )


@dataclass(frozen=True)
class CycleDecision:
    """One mode choice plus the reason (for logs/tests)."""

    mode: str
    reason: str


def choose_cycle_mode(
    facts: StackFacts,
    *,
    has_queue: bool,
    take_matched: bool,
    stopped: bool = False,
) -> CycleDecision:
    """Return the cycle mode for the given facts (precedence table).

    Order (area doc §C2 + stopped-first):
      stopped → single_target → take-miss empty → queued → empty_stack →
      user-empty → standalone.
    """
    if stopped:
        return CycleDecision(mode="stopped", reason="stopped")
    if facts.has_mem_click:
        return CycleDecision(mode="single_target", reason="mem_click")
    if (
        facts.has_take
        and not take_matched
        and not facts.user_scoped_ids
        and not has_queue
    ):
        return CycleDecision(mode="empty", reason="no_take_match")
    if has_queue:
        return CycleDecision(mode="queued", reason="queue")
    if facts.stack_empty:
        return CycleDecision(mode="empty_stack", reason="no_stack")
    if facts.user_scoped_ids:
        return CycleDecision(mode="empty", reason="empty_queue")
    return CycleDecision(mode="standalone", reason="standalone")
