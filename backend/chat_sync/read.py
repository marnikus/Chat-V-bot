"""Reading the page: paced chunks, and where a re-read overlaps the archive.

Owns: `ChunkReader` (the two nested loops — chunk loop x slice retries — and
the viewport rescue when a virtualised pane drops its nodes mid-read) and
`DeltaAligner` (what appeared ABOVE what we already stored).

Imports `modes` for the retry budget and `stores.history_repo.align_batch`;
the session arrives as a parameter, never as an import.
"""

from __future__ import annotations

import asyncio

from backend.chat_sync.modes import SLICE_RETRIES
from stores.history_repo import align_batch


class ChunkReader:
    """Read `[start, count)` in paced, retrying chunks.

    Owns the two nested loops (chunk loop × slice retries) so the sync body
    does not. Each chunk goes straight to the :class:`SyncPersister` when the
    read is streaming, or into `session.collected` when the archive has a tail
    we must align against first.
    """

    def __init__(self, session: "SyncSession"):
        self.s = session
        self.persister = session.persister

    async def read(self) -> None:
        s = self.s
        options = s.options
        start, first = s.plan.start, True            # `position` was primed
        while s.position < s.count:
            if options.stopping():
                s.result.stopped = True
                break
            records, end = await self._window(s.position, start)
            if not records:
                break
            s.scanned += len(records)
            await self._sink(records, s.position, first=first)
            s.result.chunks.append({"from": s.position, "to": end,
                                    "added": s.result.added})
            if options.backfill_older:
                await self.persister.recover(records, requeue_failed=True)
            s.position = end
            first = False
            options.progress(s.scanned, max(0, s.count - start))
            await self._pace()

    async def _window(self, position: int, start: int):
        """One slice, retried; may move the window when the page moved."""
        s, end = self.s, min(self.s.count,
                             position + int(self.s.parser.chunk_size))
        for attempt in range(SLICE_RETRIES):
            records = await s.parser.slice(position, end)
            if records:
                return records, end
            if self._may_restore_viewport(position, start, attempt):
                end = await s.restore_viewport(position)
            else:
                await asyncio.sleep(0.2)
        return [], end

    def _may_restore_viewport(self, position: int, start: int,
                              attempt: int) -> bool:
        """Only once, only at the first window of a backfill that never
        settled: the DOM lost the nodes between the settle probe and this
        read, so put the viewport back and look again."""
        s = self.s
        return bool(position == start and s.options.backfill_older
                    and not s.result.backfilled and s.before_count > 0
                    and attempt == 0)

    async def _sink(self, records, position: int, *, first: bool) -> None:
        if self.s.plan.streaming:
            await self.persister.stream_chunk(records, position, first=first)
        else:
            self.s.collected.extend(records)

    async def _pace(self) -> None:
        s = self.s
        if s.position >= s.count:
            return
        pause = s.options.pause_seconds()
        if pause:
            await asyncio.sleep(pause)


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
