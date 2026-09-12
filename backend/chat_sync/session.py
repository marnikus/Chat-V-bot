"""The shared state of one sync: what the phases agree on, and the two
opening/closing phases that only the session itself can run."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.chat_sync.options import SyncOptions
from backend.chat_sync.persist import SyncPersister
from backend.chat_sync.plan import ReadPlan, SyncPlanner
from stores.history_models import MAX_LIVE_ITEMS, SyncResult

log = logging.getLogger("chatbot")


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

    # ── collaborators ───────────────────────────────────────────
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
        await self._prepare_viewport()
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
        is defined in `backend.chat_parser`, which imports this module for the
        façade — a cycle at load time otherwise.
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
                                   require_private=options.require_private)
            if not check.ok:
                return self._refuse(check.reason)
        return True

    def _refuse(self, reason: str) -> bool:
        self.result.ok = False
        self.result.reason = reason
        return False

    async def _prepare_viewport(self) -> None:
        """`backfill_older`: visit the first message, then come back."""
        options = self.options
        self.before_count = int(self.state.get("count") or 0)
        if not options.backfill_older or options.stopping():
            return
        scroll = self.state.get("scroll") or {}
        self.old_top = int(scroll.get("top") or 0)
        moved = await self.parser.scroll_to_top()
        if not (moved or {}).get("ok") or options.stopping():
            return                                   # a page that cannot scroll
        await self._settle_at_top()

    async def _settle_at_top(self) -> None:
        await self._fetch_settled_state()
        if self._settled_ok():
            self.result.backfilled = True
            self.restored_top = self.old_top or None
            return
        self.result.backfill_pending = True
        if self.before_count > 0 and self._post_count() < self.before_count:
            await self._recover_emptied_pane()

    async def _fetch_settled_state(self) -> None:
        """Wait for the top-edge state to stabilise and install it."""
        wait = max(float(self.options.backfill_wait_s or 2.0), 4.0)
        try:
            state = await self.parser.settle_after_top(
                self.state, wait_ms=300, stable_polls=3, max_wait_s=wait,
                minimum_count=self.before_count)
        except Exception:                            # noqa: BLE001
            state = await self.parser.state()
        self.state = state if isinstance(state, dict) else self.state
        self._sync_sigs()

    def _post_count(self) -> int:
        return int(self.state.get("count") or 0)

    def _settled_ok(self) -> bool:
        after = self.state.get("scroll") or {}
        return (bool(after.get("atTop"))
                and bool(self.state.get("_settled"))
                and self._post_count() >= self.before_count)

    async def _recover_emptied_pane(self) -> None:
        """The pane emptied while it re-rendered older lines. Put the
        viewport back and read what is visible now; do NOT mark the
        full scan complete, so a later tick retries from the top."""
        await self.restore_viewport()
        fallback = await self.parser.state()
        if int((fallback or {}).get("count") or 0) > 0:
            self.state = fallback
            self._sync_sigs()

    async def restore_viewport(self, position: Optional[int] = None) -> int:
        """Put the conversation back where the user had it.

        Returns the end of the window to retry, so the caller can re-clamp it
        against a count that changed while we were restoring.
        """
        try:
            await self.parser.restore_scroll(self.old_top)
        except Exception:                            # noqa: BLE001
            pass
        state = await self.parser.state()
        count = int((state or {}).get("count") or 0)
        if count <= 0:
            return self._window_end(position)
        self.state = state
        self.count = count
        self.result.count = count
        self._sync_sigs()
        self.result.backfill_pending = True
        return self._window_end(position)

    def _window_end(self, position: Optional[int]) -> int:
        if position is None:
            return self.position
        return min(self.count, position + int(self.parser.chunk_size))

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
