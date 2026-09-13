"""Admission and completion policy for a conversation-sync session.

Imports flow to pure planning; the parser's gate is imported lazily to avoid
its facade cycle. This collaborator borrows declared public session state and
collaborators, never importing the session, Qt or services at module load.
"""

from __future__ import annotations

from backend.sync.planning import SyncPlanner


def _finish_reason(result) -> str:
    """Choose the terminal reason only when no earlier phase supplied one."""
    if result.stopped:
        return "stopped"
    return "added" if result.added else "no_new"


class SyncLifecycle:
    """Own gate-before-archive admission and final cursor/result bookkeeping."""

    def __init__(self, session: "SyncSession"):
        self.s = session

    async def prepare(self) -> bool:
        """Probe and gate before touching the viewport or the archive."""
        s = self.s
        if not await self._open_page():
            return False
        if not await self._pass_gate():
            return False
        await s.viewport.prepare()
        s.sync_state()
        await self._load_archive()
        s.plan = SyncPlanner.plan(s.state, s.cursor, s.options, count=s.count)
        s.position = s.plan.start
        return True

    async def _open_page(self) -> bool:
        s = self.s
        state = await s.parser.state() or {}
        if not int(state.get("agent") or 0):
            await s.parser.install()
            state = await s.parser.state()
        s.state = state if isinstance(state, dict) else {}
        if s.state.get("ok", True):
            return True
        s.result.ok = False
        s.result.reason = s.state.get("reason") or "no_agent"
        return False

    async def _pass_gate(self) -> bool:
        """RULE 15: the two-step private gate, before any archive access."""
        # Lazy because chat_parser delegates through the public sync facade.
        from backend.chat_parser import verify_private
        from backend.chat_text import norm

        s = self.s
        options, state = s.options, s.state
        if options.require_private and state.get("tab") != "private":
            return self._refuse("not_private")
        if options.verify_partner:
            if norm(state.get("partner")) != norm(s.nick):
                return self._refuse("partner_mismatch")
            check = verify_private(state, s.nick, options.my_nick,
                                   require_private=options.require_private)
            if not check.ok:
                return self._refuse(check.reason)
        return True

    def _refuse(self, reason: str) -> bool:
        self.s.result.ok = False
        self.s.result.reason = reason
        return False

    async def _load_archive(self) -> None:
        s = self.s
        s.person_id = await s.repo.ensure_person(s.nick)
        s.cursor = await s.repo.get_cursor(s.person_id) or {}
        s.live_baseline = int(s.cursor.get("last_ord") or 0)
        s.result.total = await self.person_total()

    async def person_total(self) -> int:
        s = self.s
        person = await s.repo.get_person_by_id(s.person_id) or {}
        return int(person.get("message_count") or 0)

    async def finish_empty(self) -> None:
        await self.s.persister.empty()
        self.s.result.reason = "empty"

    async def record_cap_gap(self) -> None:
        s = self.s
        if not s.plan.gap:
            return
        s.result.gap = True
        await s.persister.record_cap_gap()

    async def finish(self) -> None:
        s = self.s
        s.complete = (not s.result.stopped) and s.position >= s.count
        if s.result.backfilled and not s.result.stopped \
                and not s.result.backfill_pending:
            await s.persister.mark_backfilled(why="backfill")
        await s.persister.touch(s.count if s.complete else s.position,
                                complete=s.complete)
        s.result.total = await self.person_total()
        s.result.scanned = s.scanned
        if not s.result.reason:
            s.result.reason = _finish_reason(s.result)
