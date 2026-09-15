"""Queue ordering — part of RunQueueMixin, extracted by responsibility.

H-C1: queue ordering, respect Order column, repeat cycles.
Methods: _enabled_block, _unmessaged, _order_by_recency, queue_order,
_repeat_cycles, _respect_order_wanted, _rank_queue, _order_queue_by_column.

Design: docs/archive/2026-09-14-round-h/AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md H-C1
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("chatbot")

try:
    from stores.user_memory import UserRecord
except Exception:

    @dataclass
    class UserRecord:
        nick: str
        messaged: bool = False
        _fallback: str = "queue_order"


class QueueOrderMixin:
    """Queue ordering — label filter + recency + Order column respect."""

    def _enabled_block(self, block_id: str):
        """The enabled block with this id, or None — one shape, three callers."""
        return next(
            (b for b in self._stack if b.block_id == block_id and getattr(b, "enabled", True)),
            None,
        )

    def _unmessaged(self, users: list) -> list:
        """The people not yet messaged, after the label filter."""
        return self.filter_by_labels([u for u in users if not getattr(u, "messaged", False)])

    def _order_by_recency(self, users: list) -> list:
        """Newest `first_seen` first; stable, so nick stays the tie-break."""
        by_nick = sorted(users, key=lambda u: str(getattr(u, "nick", "")).casefold())
        return sorted(by_nick, reverse=True, key=lambda u: str(getattr(u, "first_seen", "") or ""))

    def queue_order(self, users: list) -> list[str]:
        """The nicks this cycle works, in the order it works them."""
        users = self._unmessaged(users)
        if self._enabled_block("SCROLL_PARSE") is not None:
            from backend.person_filter import sort_people

            users = sort_people(users)
        else:
            users = self._order_by_recency(users)
        return [getattr(u, "nick", "") for u in users]

    def _repeat_cycles(self) -> int:
        block = self._enabled_block("REPEAT_LOOP")
        try:
            return max(1, int(getattr(block, "repeat_count", 1))) if block else 1
        except (TypeError, ValueError):
            return 1

    def _respect_order_wanted(self) -> bool:
        """CLICK_USER wants the queue in the visible Order (#) column order."""
        return any(
            b.block_id == "CLICK_USER"
            and getattr(b, "respect_order", False)
            and getattr(b, "enabled", True)
            for b in self._stack
        )

    def _rank_queue(self, rows) -> list:
        """The queue in Order (#) column order, from the memory rows."""
        order = self.queue_order(rows)
        by_nick = {getattr(row, "nick", ""): row for row in rows}
        return [by_nick[nick] for nick in order if nick in by_nick]

    async def _order_queue_by_column(self, queue: list[UserRecord]) -> list[UserRecord]:
        from actions.cancellation import check_stopped

        check_stopped(self)
        if not self._respect_order_wanted() or not queue:
            return queue
        rows = await self._memory.get_all()
        check_stopped(self)
        ranked = self._rank_queue(rows)
        if ranked:
            self.log_msg.emit(
                f"🔢 Respecting the Order (#) column — running {len(ranked)} person(s) in list order (#1 first)"
            )
            if self._tracer is not None:
                self._tracer.note({"type": "queue_mode", "mode": "respect_order", "count": len(ranked)})
        return ranked or queue
