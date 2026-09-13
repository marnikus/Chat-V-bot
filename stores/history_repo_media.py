"""The backfill that gives archived media its bytes back.

The recovery half of `stores/history_repo.py`: it walks a person's rows,
re-queues the ones whose file is missing (failed, skipped, evicted or
deleted), and reports what it did, scanning in bounded passes so a huge
history cannot pin the UI. Each pass is stamped with `_scan_seq` and rows
carry `recovery_attempts`, which is what keeps a failing URL from being
retried forever inside one scan.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from stores.history_models import MessageRecord
from stores.history_repo_identity import _as_record

log = logging.getLogger("chatbot")


class MediaRecovery:
    """The backfill that gives archived media its bytes back."""

    def __init__(self, owner):
        """`owner` is the `HistoryRepo` this part borrows state from."""
        self._owner = owner

    async def recover_media(self, person_id: int, records, media=None,
                            nick: str = "", now=None,
                            requeue_failed: bool = True) -> dict:
        """Repair images/GIFs whose URL was missing or whose download failed.

        Called while a sync re-reads the DOM. It scans the saved archive for
        messages that *should* have media but are broken, matches them to the
        freshly parsed DOM record (direction + author + the on-screen clock),
        registers the real URL in the right person folder
        (`saved_media/<Latin-nick>/images|gifs/`) and re-queues failed rows so
        the normal downloader retries them.

        Broken shapes (Bug #2 audit, 2026-09-07):

        * ``media_id IS NULL`` and the row is an *empty slot* — kind
          ``image``/``gif`` with no URL, or a ``text`` row with no text
          (a media line parsed before ``app-chat-image`` rendered);
        * ``media_id`` points at a ``failed``/``skipped`` media row.

        With ``requeue_failed=False`` (the cheap automatic pass on ordinary
        ticks) only never-registered rows are repaired — known-bad downloads
        are left for the manual backfill or the "click to restore" marker, so
        a dead URL cannot trigger a download attempt every heartbeat.

        Returns ``{"repaired": n, "requeued": n, "scanned": n}``.
        """
        if media is None or not person_id:
            return {"repaired": 0, "requeued": 0, "scanned": 0}
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        # Every recovery pass gets a unique marker: the chunked top pass and
        # the newest-window pass of one backfill can run inside the same
        # second, and a shared stamp would make the second pass believe the
        # rows the first pass scanned were its own work.
        self._owner._scan_seq += 1
        marker = f"{stamp}.{self._owner._scan_seq}"
        ctx = _RecoveryPass(self, int(person_id), media, nick, stamp, marker,
                            self._records_by_key(records), requeue_failed)
        ctx.rows = await self._broken_rows(ctx)
        if not ctx.rows:
            return ctx.report()
        for row in ctx.rows:
            await self._recover_row(row, ctx)
        await ctx.finish()
        return ctx.report()

    def _records_by_key(self, records) -> dict:
        """The DOM records of this pass, keyed the way a human recognises
        a chat line: direction + author + the on-screen clock."""
        by_key: dict[str, list[MessageRecord]] = {}
        for item in (records or []):
            rec = _as_record(item)
            if not rec.media_url:
                continue
            key = self._owner._media_key(rec.direction, rec.from_nick,
                                         rec.ts_display)
            by_key.setdefault(key, []).append(rec)
        return by_key

    async def _broken_rows(self, ctx) -> list:
        """The archived rows that need a look, excluding this pass's marker.

        Rows already stamped with the marker are skipped, which is what keeps
        two passes of one backfill from re-reading each other's work.
        """
        failed_filter = (
            " OR (m.media_id IS NOT NULL AND "
            "md.state IN ('failed','skipped'))" if ctx.requeue_failed
            else "")
        return await ctx.db.fetchdicts(
            "SELECT m.id, m.ord, m.direction, m.from_nick, m.kind, m.text, "
            "m.ts_display, m.day, m.media_id, m.media_scan_at, "
            "m.media_recovered_at, m.dup_key, md.url AS media_url, "
            "md.kind AS media_kind, md.state AS media_state "
            "FROM messages m LEFT JOIN media md ON md.id = m.media_id "
            "WHERE m.person_id=? AND m.deleted_at='' "
            "AND (m.media_scan_at='' OR m.media_scan_at<>?) "
            "AND ("
            "  (m.media_id IS NULL AND (m.kind IN ('image','gif') "
            "                           OR m.text=''))"
            + failed_filter +
            ") ORDER BY m.ord",
            (ctx.person_id, ctx.marker))

    async def _recover_row(self, row, ctx) -> None:
        """One broken row: find its DOM partner and fix what can be fixed."""
        mid = row.get("media_id")
        match = self._match_row(row, ctx)
        if match:
            if mid:
                await self._repair_stamped_row(row, ctx, mid, match)
            else:
                await self._fill_empty_slot(row, ctx, match)
        elif mid:
            # We already know the URL (the download failed earlier); the page
            # does not have to be re-read to give it another chance.
            await self._retry_known_url(row, ctx, mid)
        else:
            # The DOM pass did not show a URL for this already-saved
            # image/GIF. Remember the scan so we do not search for it
            # endlessly on every backfill.
            await self._mark_scanned(row, ctx)
        ctx.touched.append(int(row["id"]))

    def _match_row(self, row, ctx) -> Optional[MessageRecord]:
        """The next unused DOM record with the same visible identity.

        Several identical lines in one window are matched in order, so two
        "photo" messages 3 seconds apart do not both repair the first row.
        """
        key = self._owner._media_key(row.get("direction"),
                                     row.get("from_nick"),
                                     row.get("ts_display"))
        matches = ctx.by_key.get(key, [])
        at = ctx.used.get(key, 0)
        if at >= len(matches):
            return None
        ctx.used[key] = at + 1
        return matches[at]

    async def _repair_stamped_row(self, row, ctx, mid, match) -> None:
        """A row that already points at a media row: re-queue or re-point."""
        existing = await ctx.media.get(mid)
        url = match.media_url
        if existing and existing.get("url") == url:
            await ctx.count_requeue(mid)
            await ctx.db.execute(
                "UPDATE messages SET media_scan_at=?, media_recovered_at=? "
                "WHERE id=?", (ctx.marker, ctx.stamp, int(row["id"])))
            return
        await self._register(row, ctx, match, media_id=mid)

    async def _fill_empty_slot(self, row, ctx, match) -> None:
        """An empty slot: a real media line to fill, or a duplicate to drop.

        If the payload-bearing line is already archived elsewhere, the slot is
        a pre-fix duplicate artefact — remove it (design §2.3, Bug #2 audit).
        """
        if ctx.known_keys is None:
            # dup_keys already archived for this person — loaded lazily, it is
            # only needed when an empty slot finds a DOM match
            ctx.known_keys = await self._all_person_keys(ctx.person_id)
        if match.dup_key in ctx.known_keys:
            await ctx.db.execute(
                "DELETE FROM messages WHERE id=? AND text='' "
                "AND media_id IS NULL", (int(row["id"]),))
            return
        await self._register(row, ctx, match, media_id=None)

    async def _register(self, row, ctx, match, media_id) -> None:
        """Register the DOM URL for this row and re-point (or rewrite) it.

        An empty slot also rewrites its identity: the old `dup_key` was
        computed from an empty payload, which would let a later append archive
        the same line a second time.
        """
        url = match.media_url
        kind = match.media_kind or match.kind
        day = str(row.get("day") or "")[:10]
        new_mid = await ctx.media.register(url, kind, nick=ctx.nick, day=day)
        if not new_mid:
            return
        await ctx.count_requeue(new_mid)
        if media_id:
            await ctx.db.execute(
                "UPDATE messages SET media_id=?, kind=?, media_scan_at=?, "
                "media_recovered_at=? WHERE id=?",
                (new_mid, kind, ctx.marker, ctx.stamp, int(row["id"])))
        else:
            await ctx.db.execute(
                "UPDATE messages SET media_id=?, kind=?, text=?, text_lc=?, "
                "dup_key=?, fp=?, media_scan_at=?, media_recovered_at=? "
                "WHERE id=?",
                (new_mid, kind, match.text, (match.text or "").lower(),
                 match.dup_key, match.ensure_fp(), ctx.marker, ctx.stamp,
                 int(row["id"])))
        ctx.repaired += 1

    async def _retry_known_url(self, row, ctx, mid) -> None:
        existing = await ctx.media.get(mid)
        if existing and existing.get("url") and ctx.requeue_failed:
            await ctx.count_requeue(mid)
        if existing:
            await self._mark_scanned(row, ctx)

    async def _mark_scanned(self, row, ctx) -> None:
        await ctx.db.execute("UPDATE messages SET media_scan_at=? WHERE id=?",
                             (ctx.marker, int(row["id"])))

    async def _all_person_keys(self, person_id: int) -> set:
        rows = await self._owner.db.fetchall(
            "SELECT dup_key FROM messages WHERE person_id=? AND dup_key<>''",
            (person_id,))
        return {r[0] for r in rows}

    async def has_repairable_media(self, person_id: int,
                                   include_failed: bool = False,
                                   rescan_after_s: int = 600) -> bool:
        """Cheap heartbeat check: is there any media row worth a repair pass?

        ``include_failed`` is True only for the manual backfill (a known-bad
        download gets another chance there, not on every tick). A row the DOM
        could not supply a URL for is skipped for `rescan_after_s` seconds so
        a permanently unrepairable line (e.g. a deleted message) cannot make
        every heartbeat re-read the newest window. The manual backfill
        deliberately ignores that grace period: the top pass of the very
        same sync may have marked a row "scanned, not found" while the row's
        DOM record only returns after the viewport is restored.
        """
        if include_failed:
            clause = ("(media_id IS NULL AND (kind IN ('image','gif') "
                      "OR text='')) OR media_id IN "
                      "(SELECT id FROM media WHERE state IN "
                      "('failed','skipped'))")
            return bool(await self._owner.db.scalar(
                f"SELECT COUNT(*) FROM messages WHERE person_id=? "
                f"AND deleted_at='' AND ({clause})", (person_id,), 0))
        cutoff = (datetime.now() -
                  timedelta(seconds=max(60, int(rescan_after_s)))
                  ).isoformat(timespec="seconds")
        clause = ("(media_id IS NULL AND (kind IN ('image','gif') "
                  "OR text='') AND (media_scan_at='' OR media_scan_at<?))")
        return bool(await self._owner.db.scalar(
            f"SELECT COUNT(*) FROM messages WHERE person_id=? AND "
            f"deleted_at='' AND ({clause})",
            (person_id, cutoff), 0))


class _RecoveryPass:
    """The state of one `recover_media` scan.

    The pass used to carry nine locals through a 170-line method: the marker
    that identifies it, the DOM records it can match against, and the three
    counters it reports. They live here so every step of the walk is a method
    of its own and the counters cannot be lost between steps.
    """

    def __init__(self, recovery, person_id, media, nick, stamp, marker,
                 by_key, requeue_failed):
        self.recovery = recovery
        self.person_id = person_id
        self.media = media
        self.nick = nick
        self.stamp = stamp
        self.marker = marker
        self.by_key = by_key
        self.requeue_failed = requeue_failed
        self.rows: list = []
        self.used: dict[str, int] = {}
        self.known_keys: Optional[set] = None
        self.touched: list[int] = []
        self.repaired = 0
        self.requeued = 0

    @property
    def db(self):
        """The archive — read through the aggregate, never copied."""
        return self.recovery._owner.db

    async def count_requeue(self, media_id) -> bool:
        """Re-queue one row and count it when that was an actual change."""
        if await self.media.requeue(media_id, "backfill_recovery"):
            self.requeued += 1
            return True
        return False

    async def finish(self) -> None:
        if not self.touched:
            return
        await self.db.commit()
        await self.recovery._owner._recount(self.person_id)

    def report(self) -> dict:
        return {"repaired": self.repaired, "requeued": self.requeued,
                "scanned": len(self.touched)}

