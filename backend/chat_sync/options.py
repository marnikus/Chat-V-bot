"""What one sync was asked to do, and what it decided to read.

Owns: `SyncOptions` (the eleven knobs, immutable) and `ReadPlan` (the planner's
verdict). Both are pure data with behaviour attached — no page, no repo, no
I/O — which is what makes the planner testable without a browser.

Imports go one way: this module imports `modes` and nothing else from the
package.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Callable, Optional

from backend.chat_sync.modes import MODE_DELTA, MODE_EMPTY, MODE_FULL


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
        """Is the user asking us to stop? A broken predicate says no.

        The fail-open rule lives in `actions.cancellation`, which owns the
        stop protocol (RULE 7), so the sync path and the scroll parser cannot
        drift apart on what a raising predicate means. The import is local:
        `actions/__init__` runs a registry scan that imports this module back,
        which is the same reason `services/run/*` imports it lazily.
        """
        from actions.cancellation import is_stop_requested
        return is_stop_requested(self.should_stop)

    def progress(self, done: int, total: int) -> None:
        """RULE 5: report each chunk as it lands — and never let a UI
        hiccup kill the read (RULE 8 of the pipeline: callbacks are wrapped).

        No log on failure here: progress ticks once per chunk, so a broken
        callback would flood the log rather than inform anyone.
        """
        from actions.cancellation import call_guarded
        call_guarded(self.on_progress, done, total)

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
