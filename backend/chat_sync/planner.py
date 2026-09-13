"""The decision: what to read, given what the archive already holds.

Owns: `SyncPlanner` (pure — a state dict and a cursor dict in, a `ReadPlan`
out) and `merge_live`, the filter that decides which appended rows may reach
the live UI channel.

Imports `options` and `modes`; imports no session and no repo, so the whole
delta algorithm is testable with two dicts.
"""

from __future__ import annotations

from typing import Optional

from backend.chat_text import signature as _signature
from backend.chat_sync.modes import (MODE_DELTA, MODE_EMPTY, MODE_FULL,
                                     MODE_UNCHANGED)
from backend.chat_sync.options import ReadPlan, SyncOptions
from stores.history_models import MAX_LIVE_ITEMS, SyncResult


class SyncPlanner:
    """The decision, as a pure function.

    `plan()` is what makes the delta logic testable without a page: it reads a
    state dict and a cursor dict and returns a :class:`ReadPlan`.
    """

    @staticmethod
    def signature(value) -> str:
        return _signature(value)

    @staticmethod
    def signatures(state: dict) -> dict:
        state = state if isinstance(state, dict) else {}
        return {"head_sig": _signature(state.get("head")),
                "tail_sig": _signature(state.get("tail")),
                "head_any": _signature(state.get("head_any")),
                "tail_any": _signature(state.get("tail_any"))}

    @staticmethod
    def nothing_moved(count: int, head_sig: str, tail_sig: str,
                      cursor: dict) -> bool:
        """The fast path: one cheap probe and no node reads at all.

        Needs all four: we have a stored position, the same number of nodes,
        the same first line and the same last line. A same-count-but-different
        tail means the pane re-rendered something in the middle, which we must
        not mistake for "already stored".
        """
        return bool(cursor.get("bootstrapped")
                    and count == cursor.get("dom_count")
                    and tail_sig and tail_sig == cursor.get("tail_sig")
                    and head_sig == cursor.get("head_sig"))

    @staticmethod
    def is_delta(count: int, head_sig: str, cursor: dict) -> bool:
        """The list only grew at the bottom, so everything before the stored
        `dom_count` is already in the archive."""
        return bool(cursor.get("bootstrapped")
                    and cursor.get("dom_count")
                    and head_sig == cursor.get("head_sig")
                    and count >= int(cursor.get("dom_count") or 0))

    @staticmethod
    def _resolved_count(state: dict, count: Optional[int]) -> int:
        """The count to plan against: the caller's override, else the pane's."""
        return int(state.get("count") or 0) if count is None else int(count)

    @staticmethod
    def _capped_start(count: int, cursor: dict, options: SyncOptions,
                      delta: bool) -> tuple[int, bool]:
        """Where the read starts, after the max-messages cap.

        A delta read resumes at the archived DOM count, a full read starts at
        0; either way the cap wins. Starting late *because of the cap* means
        messages were skipped, so the plan reports that as a gap.
        """
        start = int(cursor.get("dom_count") or 0) if delta else 0
        gap = False
        cap = int(options.max_messages or 0)
        if cap and (count - start) > cap:
            start = count - cap
            gap = True
        return start, gap

    @staticmethod
    def plan(state: dict, cursor: dict, options: Optional[SyncOptions] = None,
             *, count: Optional[int] = None) -> ReadPlan:
        state = state if isinstance(state, dict) else {}
        cursor = cursor if isinstance(cursor, dict) else {}
        options = options or SyncOptions()
        count = SyncPlanner._resolved_count(state, count)
        sigs = SyncPlanner.signatures(state)
        head_sig = sigs["head_sig"]

        if count == 0:
            return ReadPlan(mode=MODE_EMPTY, count=0, start=0, **sigs)
        if SyncPlanner.nothing_moved(count, head_sig, sigs["tail_sig"], cursor):
            return ReadPlan(mode=MODE_UNCHANGED, count=count, start=count,
                            streaming=True, **sigs)

        delta = SyncPlanner.is_delta(count, head_sig, cursor)
        start, gap = SyncPlanner._capped_start(count, cursor, options, delta)
        return ReadPlan(mode=MODE_DELTA if delta else MODE_FULL,
                        count=count, start=start, gap=gap,
                        streaming=delta or not cursor.get("tail_fps"),
                        **sigs)


def merge_live(result: SyncResult, appended, baseline: int = 0) -> None:
    """Keep only the newest records actually inserted for a live UI update.

    `baseline` is the previous archive `last_ord`: rows a backfill prepends
    (they are *older* than everything the user already had) must not be
    pushed through the live-append channel; only rows appended after the
    previous tail belong there.
    """
    for record in (getattr(appended, "records", None) or []):
        if len(result.records) >= MAX_LIVE_ITEMS:
            break
        try:
            ord_value = int(record.get("ord") or 0)
        except (TypeError, ValueError):
            ord_value = 0
        if ord_value <= baseline:
            continue
        result.records.append(record)
