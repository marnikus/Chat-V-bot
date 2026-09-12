"""The optional knobs of one sync, in one immutable place.

`backend.chat_parser.sync_conversation()` still takes them as keyword
arguments (that signature is the public contract of the archive reader);
:class:`SyncOptions` is where they land before the phases read them.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Callable, Optional


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
