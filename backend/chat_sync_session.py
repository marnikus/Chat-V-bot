"""The shared state of one sync, and its viewport mechanics.

Part of the `chat_sync_*` family (seam and family map: `backend/chat_sync.py`).
`SyncSession` is the handful of values the phases agree on and that may move
while a read is in flight; `SyncViewport` is the backfill/scroll-restore half
that used to live inside it (Round G step G2 — the session was 26 members).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.chat_sync_options import SyncOptions
from backend.parser_requests import PrivateQuery, SettleSpec
from backend.chat_sync_persist import SyncPersister, merge_live
from backend.chat_sync_plan import ReadPlan, SyncPlanner
from stores.history_models import SyncResult

log = logging.getLogger("chatbot")


class SyncViewport:
    """The backfill and scroll-restore mechanics of one session.

    Holds the session and reads/writes its fields through the reference —
    the same collaborator pattern as :class:`SyncPersister`. A virtualised
    pane can lose its nodes mid-run, so these methods mutate `state`,
    `count` and the signatures as they observe the page.
    """

    def __init__(self, session: "SyncSession"):
        self.s = session

    async def prepare_backfill(self) -> None:
        """`backfill_older`: visit the first message, then come back."""
        options = self.s.options
        self.s.before_count = int(self.s.state.get("count") or 0)
        if not options.backfill_older or options.stopping():
            return
        scroll = self.s.state.get("scroll") or {}
        self.s.old_top = int(scroll.get("top") or 0)
        moved = await self.s.parser.scroll_to_top()
        if not (moved or {}).get("ok") or options.stopping():
            return                                   # a page that cannot scroll
        await self.settle_at_top()

    async def fetch_settled_state(self) -> None:
        """Read the pane after the scroll-to-top, settling it if it can.

        A settle that raises is not fatal: fall back to a plain state read,
        and keep the previous state if even that returns a non-dict.
        """
        wait = max(float(self.s.options.backfill_wait_s or 2.0), 4.0)
        try:
            state = await self.s.parser.settle_after_top(
                self.s.state, SettleSpec(max_wait_s=wait,
                                         minimum_count=self.s.before_count))
        except Exception:                            # noqa: BLE001
            state = await self.s.parser.state()
        self.s.state = state if isinstance(state, dict) else self.s.state
        self.s._sync_sigs()

    def settled_ok(self) -> bool:
        """The backfill landed: at the top, settled, and nothing was lost."""
        after = self.s.state.get("scroll") or {}
        return (bool(after.get("atTop")) and bool(self.s.state.get("_settled"))
                and int(self.s.state.get("count") or 0) >= self.s.before_count)

    async def recover_emptied_pane(self) -> None:
        """The pane emptied while it re-rendered older lines. Put the
        viewport back and read what is visible now; do NOT mark the
        full scan complete, so a later tick retries from the top."""
        await self.restore()
        fallback = await self.s.parser.state()
        if int((fallback or {}).get("count") or 0) > 0:
            self.s.state = fallback
            self.s._sync_sigs()

    async def settle_at_top(self) -> None:
        await self.fetch_settled_state()
        if self.settled_ok():
            self.s.result.backfilled = True
            self.s.restored_top = self.s.old_top or None
            return
        self.s.result.backfill_pending = True
        if (self.s.before_count > 0
                and int(self.s.state.get("count") or 0) < self.s.before_count):
            await self.recover_emptied_pane()

    async def restore(self, position: Optional[int] = None) -> int:
        """Put the conversation back where the user had it.

        Returns the end of the window to retry, so the caller can re-clamp it
        against a count that changed while we were restoring.
        """
        try:
            await self.s.parser.restore_scroll(self.s.old_top)
        except Exception:                            # noqa: BLE001
            pass
        state = await self.s.parser.state()
        count = int((state or {}).get("count") or 0)
        if count <= 0:
            return self.window_end(position)
        self.s.state = state
        self.s.count = count
        self.s.result.count = count
        self.s._sync_sigs()
        self.s.result.backfill_pending = True
        return self.window_end(position)

    def window_end(self, position: Optional[int]) -> int:
        if position is None:
            return self.s.position
        return min(self.s.count, position + int(self.s.parser.chunk_size))


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
        self._viewport: SyncViewport = SyncViewport(self)

    # ── collaborators ────────────────────────────────────────────
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

    # ── the opening phases ───────────────────────────────────────
    async def prepare(self) -> bool:
        """Probe the page, pass the gate, settle the viewport, load the cursor.

        False means the caller must return `result` as it stands (refused or
        broken page) — nothing has been written.
        """
        if not await self._open_page():
            return False
        if not await self._pass_gate():
            return False
        await self._viewport.prepare_backfill()
        self._sync_sigs()
        await self._load_archive()
        self.plan = SyncPlanner.plan(self.state, self.cursor, self.options,
                                    count=self.count)
        # the read starts where the plan says: `start` is 0 for a full re-read
        # and the stored `dom_count` (or the trimmed cap) otherwise
        self.position = self.plan.start
        return True

    async def _open_page(self) -> bool:
        state = await self.parser.state() or {}
        if not int(state.get("agent") or 0):
            await self.parser.install()
            state = await self.parser.state()
        self.state = state if isinstance(state, dict) else {}
        if self.state.get("ok", True):
            return True
        self.result.ok = False
        self.result.reason = self.state.get("reason") or "no_agent"
        return False

    async def _pass_gate(self) -> bool:
        """RULE 15: the two-step private-chat gate, before any write.

        `verify_private` is imported here rather than at module top: the gate
        is defined in `backend.chat_parser`, which imports the sync family
        for the façade — a cycle at load time otherwise.
        """
        from backend.chat_parser import verify_private     # cycle, see above
        from backend.chat_text import norm

        options, state = self.options, self.state
        if options.require_private and state.get("tab") != "private":
            return self._refuse("not_private")
        if options.verify_partner:
            if norm(state.get("partner")) != norm(self.nick):
                return self._refuse("partner_mismatch")
            check = verify_private(state, self.nick, options.my_nick,
                                   PrivateQuery(require_private=options.require_private))
            if not check.ok:
                return self._refuse(check.reason)
        return True

    def _refuse(self, reason: str) -> bool:
        self.result.ok = False
        self.result.reason = reason
        return False

    async def restore_viewport(self, position: Optional[int] = None) -> int:
        """Put the conversation back where the user had it.

        Returns the end of the window to retry, so the caller can re-clamp it
        against a count that changed while we were restoring. The mechanics
        live in :class:`SyncViewport`; this is the pinned public door.
        """
        return await self._viewport.restore(position)

    def _sync_sigs(self) -> None:
        """Re-read the four cursor signatures from the current state."""
        sigs = SyncPlanner.signatures(self.state)
        self.head_sig = sigs["head_sig"]
        self.tail_sig = sigs["tail_sig"]
        self.head_any = sigs["head_any"]
        self.tail_any = sigs["tail_any"]
        self.count = int(self.state.get("count") or 0)
        self.result.count = self.count

    async def _load_archive(self) -> None:
        self.person_id = await self.repo.ensure_person(self.nick)
        self.cursor = await self.repo.get_cursor(self.person_id) or {}
        self.live_baseline = int(self.cursor.get("last_ord") or 0)
        self.result.total = await self.person_total()

    async def person_total(self) -> int:
        person = await self.repo.get_person_by_id(self.person_id) or {}
        return int(person.get("message_count") or 0)

    # ── the closing phases ───────────────────────────────────────
    async def finish_empty(self) -> None:
        await self.persister.empty()
        self.result.reason = "empty"

    async def record_cap_gap(self) -> None:
        if not self.plan.gap:
            return
        self.result.gap = True
        await self.persister.record_cap_gap()

    async def restore_if_needed(self) -> None:
        if self.restored_top is None:
            return
        try:
            await self.parser.restore_scroll(self.restored_top)
        except Exception:                            # noqa: BLE001
            log.debug("could not restore scroll position for %s", self.nick)

    async def finish(self) -> None:
        self.complete = (not self.result.stopped) and self.position >= self.count
        if self.result.backfilled and not self.result.stopped \
                and not self.result.backfill_pending:
            await self.persister.mark_backfilled(why="backfill")
        await self.persister.touch(self.count if self.complete else self.position,
                                   complete=self.complete)
        self.result.total = await self.person_total()
        self.result.scanned = self.scanned
        if not self.result.reason:
            self.result.reason = self._default_reason()

    def _default_reason(self) -> str:
        if self.result.stopped:
            return "stopped"
        return "added" if self.result.added else "no_new"
