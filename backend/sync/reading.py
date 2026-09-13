"""Paced range reading and buffered alignment for conversation sync.

Imports point to the archive alignment helper and standard-library asyncio,
never to the runtime session, facade, Qt or services. Session/repository writes
are delegated through the supplied persister, not duplicated here. Shared
stop helpers are imported lazily at runtime to avoid action-registry cycles.
"""

from __future__ import annotations

import asyncio

from stores.history_repo import align_batch

# A virtualized pane can lose its nodes between the state and slice probes.
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

    # ideal-size: 21 lines reason=completed chunks must retain the ordered
    # write/progress/position contract before a cooperative stop takes effect.
    async def read(self) -> None:
        s = self.s
        options = s.options
        start, first = s.plan.start, True            # `position` was primed
        while s.position < s.count:
            if self._stopping():
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
        self._stopping()

    async def _window(self, position: int, start: int):
        """One slice, retried; may move the window when the page moved."""
        s, end = self.s, min(self.s.count,
                             position + int(self.s.parser.chunk_size))
        for attempt in range(SLICE_RETRIES):
            if self._stopping():
                break
            records = await s.parser.slice(position, end)
            if records:
                return records, end
            if self._stopping():
                break
            if self._may_restore_viewport(position, start, attempt):
                end = await s.restore_viewport(position)
            else:
                await self._pause(0.2)
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
            await self._pause(pause)


    def _stopping(self) -> bool:
        """Latch a stop so an interrupted wait cannot become a normal EOF."""
        result = self.s.result
        result.stopped = result.stopped or self.s.options.stopping()
        return result.stopped

    async def _pause(self, delay: float) -> None:
        """Interrupt retry/pacing waits without treating cancellation as stop."""
        if not callable(self.s.options.should_stop):
            await asyncio.sleep(delay)
            return
        # Lazy: importing actions auto-scans blocks that import the sync facade.
        from actions.cancellation import RunStopped, sleep_with_stop

        try:
            await sleep_with_stop(delay, self.s.options.stopping)
        except RunStopped:
            self.s.result.stopped = True


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
