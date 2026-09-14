"""Take phase — part of RunQueueMixin, extracted by responsibility.

H-C1: Pick Person phase (TAKE_PERSON block).
Methods: _run_take_phase, _take_one_block.

Design: docs/archive/2026-09-14-round-h/AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md H-C1
"""

from __future__ import annotations

import logging

log = logging.getLogger("chatbot")


class TakePhaseMixin:
    """Pick Person phase — remembers one nick per cycle."""

    async def _run_take_phase(self) -> bool:
        from actions.cancellation import check_stopped

        check_stopped(self)
        try:
            rows = await self._memory.get_all()
        except Exception as exc:
            log.warning("Pick Person phase could not read the list: %s", exc)
            self.debug_msg.emit(
                f"      ❌ Pick Person: cannot read the People list ({exc})", "error"
            )
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
                "fields will resolve to it"
            )
            self.note_selected(nick)
            return True
        self.log_msg.emit(
            "⚠ Pick Person: no "
            + (getattr(block, "mode_phrase", "") or "matching person")
            + " in the list — skipped (previous selection kept)"
        )
        return False
