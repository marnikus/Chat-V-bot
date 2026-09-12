"""The write phase: every repo write the sync makes, in one place."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:                                  # pragma: no cover
    from backend.chat_sync.session import SyncSession

log = logging.getLogger("chatbot")


class SyncPersister:
    """Every write to the archive, in one place.

    `HistoryRepo` is the only thing that may touch the database, so the sync
    never calls it from two different layers: recovery, gap notes, cursor
    bookkeeping and the "this conversation is fully backfilled" flag all live
    here. Each one is best-effort — a bookkeeping failure must never turn a
    successful read into an exception (RULE 4: an empty/partial result is
    reported as such, not as a crash).
    """

    def __init__(self, session: "SyncSession"):
        self.s = session

    # ── cursor bookkeeping ───────────────────────────────────────
    @staticmethod
    def cursor_kwargs(signatures, dom_count: int, *, complete: bool = True
                      ) -> dict:
        return {"dom_count": dom_count,
                "head_sig": getattr(signatures, "head_sig", ""),
                "tail_sig": (getattr(signatures, "tail_sig", "")
                             if complete else ""),
                "head_any": getattr(signatures, "head_any", ""),
                "tail_any": (getattr(signatures, "tail_any", "")
                             if complete else "")}

    def _cursor_kwargs(self, dom_count: int, *, complete: bool) -> dict:
        return self.cursor_kwargs(self.s, dom_count, complete=complete)

    async def touch(self, dom_count: int, *, complete: bool = True) -> None:
        """Write the read position without appending any record."""
        s = self.s
        await s.repo.append(s.nick, [], my_nick=s.options.my_nick,
                            **self._cursor_kwargs(dom_count, complete=complete),
                            now=s.options.now)

    async def mark_backfilled(self, *, why: str) -> None:
        try:
            await self.s.repo.mark_backfilled(self.s.person_id)
        except Exception as exc:                     # noqa: BLE001
            log.debug("could not mark %s fully backfilled (%s): %s",
                      self.s.nick, why, exc)

    async def empty(self) -> None:
        """An empty pane: store the shape, and only trust "complete" when the
        pane really has nothing to scroll."""
        s, result = self.s, self.s.result
        await self.touch(0)
        scroll = (s.state or {}).get("scroll") or {}
        truly_empty = int(scroll.get("height") or 0) <= 0
        if result.backfilled and truly_empty and not result.stopped:
            await self.mark_backfilled(why="empty pane")

    async def record_cap_gap(self) -> None:
        """`max_messages` trimmed the window: note the hole we left behind."""
        s = self.s
        after = await s.repo._last_ord(s.person_id)
        await s.repo.record_gap(
            s.person_id, after, "capped",
            f"only the newest {int(s.options.max_messages or 0)} messages "
            "were collected")

    # ── records ──────────────────────────────────────────────────
    async def stream_chunk(self, records, position: int, *, first: bool) -> None:
        """Append one chunk as it lands (the delta / first-ever-read path)."""
        s = self.s
        appended = await s.repo.append(
            s.nick, records, my_nick=s.options.my_nick,
            align=first and not s.delta and not s.result.gap,
            expect_idx=position if (s.delta or not first or s.result.gap)
            else None,
            now=s.options.now)
        s.absorb(appended)

    async def write_batch(self, records) -> None:
        """Append a whole re-read, letting the archive align it."""
        s = self.s
        appended = await s.repo.append(s.nick, records,
                                       my_nick=s.options.my_nick, align=True,
                                       now=s.options.now)
        s.absorb(appended)

    async def write_backfill(self, records) -> None:
        """Prepend the lines that appeared ABOVE what we already stored."""
        s = self.s
        appended = await s.repo.append(s.nick, records,
                                       my_nick=s.options.my_nick, prepend=True,
                                       now=s.options.now)
        s.absorb(appended)

    # ── media ────────────────────────────────────────────────────
    async def recover(self, records, *, requeue_failed: bool) -> None:
        s = self.s
        if s.options.media is None or not records:
            return
        try:
            stats = await s.repo.recover_media(
                s.person_id, records, media=s.options.media, nick=s.nick,
                now=s.options.now, requeue_failed=requeue_failed)
        except Exception as exc:                     # noqa: BLE001
            log.debug("media recovery for %s failed: %s", s.nick, exc)
            return
        s.result.media_repaired += int(stats.get("repaired") or 0)
        s.result.media_requeued += int(stats.get("requeued") or 0)

    async def repair_tail(self) -> None:
        """The newest window, after the viewport went back.

        A scroll-to-top pass drops the newest nodes from the DOM, so a broken
        media line at the BOTTOM of the chat never met its DOM record during
        the reads above. One more pass over the tail repairs it — and it also
        runs on ordinary ticks, which is how a media line that rendered after
        its first parse is repaired within one heartbeat instead of never.
        """
        s = self.s
        if s.options.media is None or s.options.stopping():
            return
        try:
            if not await s.repo.has_repairable_media(
                    s.person_id, include_failed=bool(s.options.backfill_older)):
                return
            tail_state = await s.parser.state()
            tail_count = int((tail_state or {}).get("count") or 0)
            if tail_count <= 0:
                return
            window = max(int(s.parser.chunk_size), 80)
            records = await s.parser.slice(max(0, tail_count - window),
                                           tail_count)
            if records:
                await self.recover(records,
                                   requeue_failed=bool(s.options.backfill_older))
        except Exception as exc:                     # noqa: BLE001
            log.debug("tail media recovery for %s failed: %s", s.nick, exc)
