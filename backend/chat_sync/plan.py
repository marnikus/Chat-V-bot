"""What to read: the modes, the ReadPlan, and the pure SyncPlanner.

`plan()` is what makes the delta logic testable without a page: it reads a
state dict and a cursor dict and returns a :class:`ReadPlan`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.chat_sync.options import SyncOptions
from backend.chat_text import signature as _signature

#: What the archive should do with what we are about to read.
MODE_EMPTY = "empty"            # the pane holds nothing
MODE_UNCHANGED = "unchanged"    # nothing moved — ZERO node reads
MODE_DELTA = "delta"            # the head is intact, the tail grew
MODE_FULL = "full"              # re-read the visible range and align it


@dataclass(frozen=True, slots=True)
class ReadPlan:
    """What `SyncPlanner` decided: the mode, the window, and the signatures."""

    mode: str = MODE_FULL
    count: int = 0
    start: int = 0
    #: True → append per chunk; False → read everything, then align once
    streaming: bool = True
    gap: bool = False
    head_sig: str = ""
    tail_sig: str = ""
    head_any: str = ""
    tail_any: str = ""

    @property
    def delta(self) -> bool:
        return self.mode == MODE_DELTA

    @property
    def is_empty(self) -> bool:
        return self.mode == MODE_EMPTY

    @property
    def signatures(self) -> dict:
        return {"head_sig": self.head_sig, "tail_sig": self.tail_sig,
                "head_any": self.head_any, "tail_any": self.tail_any}

    def cursor_kwargs(self, dom_count: int, *, complete: bool = True) -> dict:
        """The bookkeeping `repo.append([], …)` needs.

        An incomplete read must not advertise a tail: the whole "nothing
        moved" fast path trusts `tail_sig`, and promising it after a partial
        read is how messages get skipped forever.
        """
        return {"dom_count": dom_count, "head_sig": self.head_sig,
                "tail_sig": self.tail_sig if complete else "",
                "head_any": self.head_any,
                "tail_any": self.tail_any if complete else ""}


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
        return int(state.get("count") or 0) if count is None else int(count)

    @staticmethod
    def _capped_start(count: int, cursor: dict, options: SyncOptions,
                      delta: bool) -> tuple[int, bool]:
        """(start, gap): the max-messages cap; a capped start means the read
        skipped history (gap=True)."""
        start = int(cursor.get("dom_count") or 0) if delta else 0
        cap = int(options.max_messages or 0)
        if cap and (count - start) > cap:
            return count - cap, True
        return start, False

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
