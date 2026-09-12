"""The read phase: [start, count) in paced, retrying chunks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:                                  # pragma: no cover
    from backend.chat_sync.session import SyncSession

#: A virtualised pane can drop its message nodes between a state() probe and
#: the slice() that follows. Do not archive "0" on the first read — retry the
#: range a few times (and restore the viewport once) before giving up.
SLICE_RETRIES = 4


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
