"""Options and pure read-window planning for conversation synchronization.

Imports flow to standard-library types and backend.chat_text only: no Qt,
parser, runtime session, service or storage dependencies. Runtime phases use
these immutable values; this module never performs a page read or DB write.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Callable, Optional

from backend.chat_text import signature as _signature

MODE_EMPTY = "empty"            # the pane holds nothing
MODE_UNCHANGED = "unchanged"    # nothing moved — ZERO node reads
MODE_DELTA = "delta"            # the head is intact, the tail grew
MODE_FULL = "full"              # re-read the visible range and align it


@dataclass(frozen=True, slots=True)
class SyncOptions:
    """The eleven optional knobs of one sync, in one immutable place.

    `backend.chat_parser.sync_conversation()` still takes them as keyword
    arguments (that signature is the public contract of the archive reader);
    this is where they land before the phases read them.
    """

    my_nick: str = ""
    require_private: bool = False
    verify_partner: bool = False
    max_messages: Optional[int] = None
    #: None = "whatever the parser is configured with"
    chunk_pause_ms: Optional[int] = None
    should_stop: Optional[Callable[[], bool]] = None
    on_progress: Optional[Callable[[int, int], None]] = None
    now: Optional[datetime] = None
    backfill_older: bool = False
    backfill_wait_s: float = 2.0
    media: Any = None

    # ── construction from the legacy keyword call ────────────────
    @classmethod
    def from_kwargs(cls, **kwargs) -> "SyncOptions":
        """Build from `sync_conversation`'s keyword arguments.

        Unknown keys are dropped rather than raising: the run engine and the
        collector both forward option dicts that may carry retired keys.
        """
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in kwargs.items() if k in known})

    def for_parser(self, parser=None, now: Optional[datetime] = None
                   ) -> "SyncOptions":
        """Resolve the two values that depend on the parser/clock."""
        patch: dict = {}
        if self.chunk_pause_ms is None:
            patch["chunk_pause_ms"] = getattr(parser, "chunk_pause_ms", 0) or 0
        patch["chunk_pause_ms"] = max(0, int(patch.get("chunk_pause_ms",
                                                        self.chunk_pause_ms) or 0))
        if self.now is None:
            patch["now"] = now or datetime.now()
        return replace(self, **patch)

    # ── behaviour the phases ask for ─────────────────────────────
    def pause_seconds(self, parser=None) -> float:
        ms = self.chunk_pause_ms
        if ms is None:
            ms = getattr(parser, "chunk_pause_ms", 0) or 0
        return max(0, int(ms or 0)) / 1000.0

    def stopping(self) -> bool:
        """Is the user asking us to stop? A broken predicate says no."""
        predicate = self.should_stop
        if not callable(predicate):
            return False
        try:
            return bool(predicate())
        except Exception:                            # noqa: BLE001
            return False

    def progress(self, done: int, total: int) -> None:
        """RULE 5: report each chunk as it lands — and never let a UI
        hiccup kill the read (RULE 8 of the pipeline: callbacks are wrapped)."""
        if self.on_progress is None:
            return
        try:
            self.on_progress(done, total)
        except Exception:                            # noqa: BLE001
            pass

    def cursor_time(self) -> Optional[datetime]:
        return self.now


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

    # ideal-size: 21 lines reason=immutable four-mode return contract keeps
    # each mode and its cursor-signature payload explicit in one decision.
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
