"""The align phase: where a freshly read conversation continues the
stored one."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stores.history_repo import align_batch

if TYPE_CHECKING:                                  # pragma: no cover
    from backend.chat_sync.session import SyncSession


class DeltaAligner:
    """Where a freshly read conversation continues the stored one."""

    @staticmethod
    def split(collected, cursor: dict) -> list:
        """The records that belong BEFORE what we already stored.

        Empty unless the alignment found a real overlap: with no shared tail
        there is nothing proving where the batch starts, so everything is
        written as one append and `HistoryRepo` records the gap itself.
        """
        if not collected:
            return []
        tail = (cursor or {}).get("tail_keys") or (cursor or {}).get("tail_fps") \
            or []
        alignment = align_batch([r.dup_key for r in collected], tail)
        if not alignment.start or alignment.gap:
            return []
        return list(collected[:alignment.start])

    async def apply(self, session: "SyncSession") -> None:
        """Write the buffered re-read, then prepend its older prefix."""
        s = session
        if s.plan.streaming or not s.collected:
            return
        await s.persister.write_batch(s.collected)
        older = self.split(s.collected, s.cursor)
        if older:
            await s.persister.write_backfill(older)
        if s.options.backfill_older:
            await s.persister.recover(s.collected, requeue_failed=True)
