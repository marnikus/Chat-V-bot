"""Shared sync-session state and explicit compatibility entry points.

Imports flow to lifecycle, viewport and persistence collaborators. They borrow
this dataclass's public state but never import it. Frozen public session methods
remain explicit adapters; policy lives on the collaborators, not in mixins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from backend.sync.lifecycle import SyncLifecycle
from backend.sync.persistence import SyncPersister, merge_live
from backend.sync.planning import MODE_UNCHANGED, ReadPlan, SyncOptions, SyncPlanner
from backend.sync.reading import ChunkReader, DeltaAligner
from backend.sync.viewport import SyncViewport
from stores.history_models import SyncResult


# ideal-size: >10 methods reason=11 frozen public/hook methods preserve the
# session API; sync_state is the explicit shared-state refresh seam for phases.
@dataclass
class SyncSession:
    """The state one sync shares between its phases.

    Not thread-local magic — just the handful of values that the phases agree
    on and that may move while a read is in flight (`count`, the signatures).
    """

    parser: Any
    repo: Any
    nick: str
    options: SyncOptions = field(default_factory=SyncOptions)
    result: SyncResult = field(default=None)          # built in __post_init__

    state: dict = field(default_factory=dict)
    plan: Optional[ReadPlan] = None
    cursor: dict = field(default_factory=dict)
    person_id: int = 0
    live_baseline: int = 0
    before_count: int = 0
    old_top: int = 0
    restored_top: Optional[int] = None
    count: int = 0
    head_sig: str = ""
    tail_sig: str = ""
    head_any: str = ""
    tail_any: str = ""
    scanned: int = 0
    position: int = 0
    collected: list = field(default_factory=list)
    complete: bool = False

    def __post_init__(self):
        self.options = self.options.for_parser(self.parser)
        if self.result is None:
            self.result = SyncResult(ok=True, nick=self.nick,
                                     my_nick=self.options.my_nick)
        self._persister: SyncPersister = SyncPersister(self)
        self.viewport = SyncViewport(self)
        self.lifecycle = SyncLifecycle(self)

    @property
    def persister(self) -> SyncPersister:
        return self._persister

    @property
    def delta(self) -> bool:
        return bool(self.plan and self.plan.delta)

    def absorb(self, appended) -> None:
        """Fold one `AppendResult` into the outcome the caller sees."""
        self.result.added += getattr(appended, "added", 0) or 0
        self.result.gap = self.result.gap or bool(getattr(appended, "gap", False))
        merge_live(self.result, appended, self.live_baseline)

    def sync_state(self) -> None:
        """Re-read the four cursor signatures from the current state."""
        sigs = SyncPlanner.signatures(self.state)
        self.head_sig = sigs["head_sig"]
        self.tail_sig = sigs["tail_sig"]
        self.head_any = sigs["head_any"]
        self.tail_any = sigs["tail_any"]
        self.count = int(self.state.get("count") or 0)
        self.result.count = self.count

    async def prepare(self) -> bool:
        """Preserve the public admission hook; lifecycle owns its gate ordering."""
        return await self.lifecycle.prepare()

    async def restore_viewport(self, position: Optional[int] = None) -> int:
        """Preserve the reader/public restore hook and its clamped end result."""
        return await self.viewport.restore(position)

    async def person_total(self) -> int:
        """Read the archive total through the lifecycle owner."""
        return await self.lifecycle.person_total()

    async def finish_empty(self) -> None:
        """Preserve empty-pane completion without claiming a successful read."""
        return await self.lifecycle.finish_empty()

    async def record_cap_gap(self) -> None:
        """Preserve cap-gap bookkeeping before the first archive write."""
        return await self.lifecycle.record_cap_gap()

    async def restore_if_needed(self) -> None:
        """Preserve the public final-restore hook without adding cleanup paths."""
        return await self.viewport.restore_if_needed()

    async def finish(self) -> None:
        """Preserve the final cursor/result hook after reading and restoration."""
        return await self.lifecycle.finish()


# quality-override: params=5 reason=frozen public run_sync accepts parser, repo, nick, typed options and legacy keyword settings
# ideal-size: 25 lines reason=ordered sync phases and the three early-result
# contracts remain explicit at the public entry point.
async def run_sync(parser, repo, nick: str,
                   options: Optional[SyncOptions] = None, **legacy) -> SyncResult:
    """Bring the archive up to date with what the page currently shows.

    `backend.chat_parser.sync_conversation()` is the public entry point and
    forwards its keyword arguments; `options` is the typed seam new callers
    should use.
    """
    session = SyncSession(parser, repo, nick,
                          options or SyncOptions.from_kwargs(**legacy))
    if not await session.prepare():
        return session.result
    if session.plan.is_empty:
        await session.finish_empty()
        return session.result
    if session.plan.mode == MODE_UNCHANGED:
        session.result.reason = "unchanged"
        return session.result
    await session.record_cap_gap()
    await ChunkReader(session).read()
    await DeltaAligner().apply(session)
    await session.restore_if_needed()
    await session.persister.repair_tail()
    await session.finish()
    return session.result
