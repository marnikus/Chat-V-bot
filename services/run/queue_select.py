"""Who a cycle works, and in what order.

Three mixins over one responsibility: turn the people list into the queue this
cycle runs.

* `LabelGateMixin` — apply the label filter. Fail-open: a filter that raises
  keeps the person (RULE 4 — "broken" must not look like "not wanted").
* `QueueOrderMixin` — decide the order (Scroll & Parse's sort, the visible
  Order (#) column, or newest-first), and own the pause gate every loop waits
  on (RULE 7).
* `TakePhaseMixin` — run the Pick Person blocks that choose one nick.

All three are internal (every name but `label_allows`, `filter_by_labels` and
`queue_order` is private) and reach the engine through `RunCoordinator`'s
bases, exactly like the other run mixins.

Import direction: `logging` and the shared `UserRecord` at module level;
`backend.person_filter` and `actions.cancellation` inside methods so
`import services.run` stays light (actions/__init__ scans every block module).
"""

from __future__ import annotations

import asyncio
import logging

from .requests import UserRecord

log = logging.getLogger("chatbot")


class LabelGateMixin:
    """The label filter, applied fail-open; mixed into ``RunCoordinator``."""

    def label_allows(self, nick) -> bool:
        if not callable(self.label_filter):
            return True
        try:
            return bool(self.label_filter(nick))
        except Exception as exc:
            log.warning("label filter failed for %r: %s", nick, exc)
            return True

    def filter_by_labels(self, users: list, announce: bool = False) -> list:
        if not callable(self.label_filter):
            return list(users or [])
        kept, skipped = [], []
        for user in users or []:
            nick = getattr(user, "nick", user)
            if self.label_allows(nick):
                kept.append(user)
            else:
                skipped.append(str(nick))
        if skipped and announce:
            self._announce_label_skips(skipped)
        return kept

    def _label_reason_for(self, nick) -> str:
        """Why the label filter rejected one nick (fail-open to no reason)."""
        if not callable(self.label_reason):
            return ""
        try:
            return str(self.label_reason(nick) or "")
        except Exception:
            return ""

    def _announce_label_skips(self, skipped: list) -> None:
        """One info line naming the first few rejected people (+N more)."""
        samples = []
        for nick in skipped[:5]:
            why = self._label_reason_for(nick)
            samples.append(f"{nick}{f' ({why})' if why else ''}")
        more = (f" +{len(skipped) - len(samples)} more"
                if len(skipped) > len(samples) else "")
        self.debug_msg.emit(f"🏷 Label filter skipped {len(skipped)} person(s): "
                            + ", ".join(samples) + more, "info")


class QueueOrderMixin:
    """Queue order and the pause gate; mixed into ``RunCoordinator``."""

    def _enabled_block(self, block_id: str):
        """The enabled block with this id, or None — one shape, four callers."""
        return next((b for b in self._stack if b.block_id == block_id
                     and getattr(b, "enabled", True)), None)

    def _unmessaged(self, users: list) -> list:
        """The people not yet messaged, after the label filter."""
        return self.filter_by_labels(
            [u for u in users if not getattr(u, "messaged", False)])

    def _order_by_recency(self, users: list) -> list:
        """Newest `first_seen` first; stable, so nick stays the tie-break."""
        by_nick = sorted(users,
                         key=lambda u: str(getattr(u, "nick", "")).casefold())
        return sorted(by_nick, reverse=True,
                      key=lambda u: str(getattr(u, "first_seen", "") or ""))

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
        return any(b.block_id == "CLICK_USER" and getattr(b, "respect_order", False)
                   and getattr(b, "enabled", True) for b in self._stack)

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
            self.log_msg.emit(f"🔢 Respecting the Order (#) column — running {len(ranked)} person(s) in list order (#1 first)")
            if self._tracer is not None:
                self._tracer.note({"type": "queue_mode", "mode": "respect_order", "count": len(ranked)})
        return ranked or queue

    async def _wait_if_paused(self) -> None:
        while self._paused and not self._stop_requested:
            await asyncio.sleep(0.2)


class TakePhaseMixin:
    """The Pick Person phase; mixed into ``RunCoordinator``."""

    async def _run_take_phase(self) -> bool:
        from actions.cancellation import check_stopped
        check_stopped(self)
        try:
            rows = await self._memory.get_all()
        except Exception as exc:
            log.warning("Pick Person phase could not read the list: %s", exc)
            self.debug_msg.emit(f"      ❌ Pick Person: cannot read the People list ({exc})", "error")
            return False
        check_stopped(self)
        matched = False
        for block in self._stack:
            check_stopped(self)
            if block.block_id != "TAKE_PERSON" or not getattr(block, "enabled", True):
                continue
            if self._take_one_block(block, rows):
                matched = True
        return matched

    def _take_one_block(self, block, rows) -> bool:
        """One Pick Person block's choice; True when it remembered someone."""
        try:
            nick = block.choose(rows, self)
        except Exception as exc:
            log.warning("Pick Person failed: %s", exc)
            self.debug_msg.emit(f"      ❌ Pick Person raised: {exc}", "error")
            return False
        if nick:
            self.log_msg.emit(
                f"🎯 Pick Person: remembering “{nick}” — {{nick}} in later "
                f"fields will resolve to it")
            self.note_selected(nick)
            return True
        self.log_msg.emit(
            "⚠ Pick Person: no "
            + (getattr(block, "mode_phrase", "") or "matching person")
            + " in the list — skipped (previous selection kept)")
        return False
