"""Archive phases for a verified collector heartbeat."""

import logging
from .state import CollectorState

log = logging.getLogger("chatbot")


class CollectorArchive:
    @staticmethod
    async def prepare(collector, state, nick, _signature):
        head_sig = _signature(state.get("head"))
        tail_sig = _signature(state.get("tail"))
        head_any = _signature(state.get("head_any"))
        tail_any = _signature(state.get("tail_any"))

        # The partner may have RENAMED themselves: identical pane content
        # under a new title is the same conversation, so the archive
        # continues under the new nick instead of forking an empty person
        # (bug report 2026-09-08, "diff name as Person").
        if collector._nick and nick != collector._nick:
            try:
                if await collector.repo.rename_if_same_conversation(
                    collector._nick,
                    nick,
                    head_sig,
                    tail_sig,
                    head_any=head_any,
                    tail_any=tail_any,
                    dom_count=int(state.get("count") or 0),
                    pane_same=bool(state.get("pane_same")),
                ):
                    collector._log(
                        f"Partner “{collector._nick}” is now “{nick}” — "
                        "the history continues",
                        "info",
                        nick,
                    )
            except Exception as e:  # noqa: BLE001
                log.debug("rename check for %s failed: %s", nick, e)

        # A verified private tab (active tab = private, 2 participants, title
        # names the partner) is enough to create the person in BOTH stores.
        # The author gate below protects the message rows from a mixed pane;
        # the People row itself is safe even before that check passes.
        person_id = await collector.repo.ensure_person(nick)
        remembered = await collector._remember_partner(nick, state)
        collector._log(f"Partner “{nick}”: {remembered}", "info", nick)

        return person_id, head_sig, tail_sig

    @staticmethod
    async def advance(collector, state, nick, my_nick, person_id, head_sig, tail_sig):
        cursor = await collector.repo.get_cursor(person_id)
        count = int(state.get("count") or 0)
        unchanged = (
            cursor["bootstrapped"]
            and count == cursor["dom_count"]
            and tail_sig
            and tail_sig == cursor["tail_sig"]
            and head_sig == cursor["head_sig"]
        )
        person = await collector.repo.get_person_by_id(person_id) or {}
        collector._total = int(person.get("message_count") or 0)
        if unchanged:
            collector._added = 0
            collector._last_sync_reason = "unchanged_cursor"
            collector._last_sync_added = 0
            collector._last_sync_count = count
            # An idle conversation must not stall the media downloader: a
            # backfill can re-queue dozens of rows and `process_pending`
            # only takes 25 per pass, so the rest need the next tick even
            # when nothing in the chat changed (Bug #2, 2026-09-07).
            await CollectorArchive.drain_media(collector)
            return collector._set(CollectorState.NO_NEW, collector._no_new_text())

        return await CollectorArchive.collect(collector, nick, my_nick, cursor)

    @staticmethod
    async def collect(collector, nick, my_nick, cursor):
        bootstrap = not cursor["bootstrapped"]
        full_scan_complete = bool(cursor.get("full_scan_complete"))
        want_backfill = (
            bool(collector._settings.get("auto_backfill", True))
            and not full_scan_complete
            and not collector._backfill_pending
        ) or collector._force_backfill
        collector._force_backfill = False
        collector._set(
            CollectorState.BOOTSTRAPPING if bootstrap else CollectorState.COLLECTING,
            f"Collecting from {nick}…",
        )

        result = await collector._sync(
            nick, my_nick, bootstrap, backfill_older=want_backfill
        )
        return await CollectorArchive.finish(collector, nick, result)

    @staticmethod
    async def finish(collector, nick, result):
        collector._backfill_pending = bool(result.backfill_pending)
        collector._last_sync_reason = str(result.reason or "")
        collector._last_sync_added = int(result.added or 0)
        collector._last_sync_count = int(result.count or 0)
        collector._added = result.added
        collector._total = result.total
        if result.media_repaired or result.media_requeued:
            collector._last_media_repaired = int(result.media_repaired or 0)
            collector._last_media_requeued = int(result.media_requeued or 0)
            collector._log(
                f"Media recovery: repaired {result.media_repaired} "
                f"message(s), re-queued {result.media_requeued} "
                f"download(s)",
                "success",
                nick,
            )
        await CollectorArchive.drain_media(collector)

        suffix = " (throttled — a run is active)" if collector._throttled else ""
        if result.added:
            await collector._notify_appended(
                nick, list(result.records[:200]), result.added, result.total
            )
            collector._log(
                f"Archived {result.added} new message(s) (total {result.total})",
                "success",
                nick,
            )
            return collector._set(
                CollectorState.COLLECTED,
                f"Collected {result.added} new "
                f"message{'s' if result.added != 1 else ''} "
                f"from {nick}{suffix}",
            )
        if not result.ok:
            collector._log(f"Sync failed for “{nick}” ({result.reason})", "error", nick)
            return collector._set(CollectorState.NOT_PRIVATE, "Not in private tab now")
        collector._log(
            f"No new messages ({result.reason}, page count "
            f"{result.count}, added {result.added})",
            "info",
            nick,
        )
        return collector._set(CollectorState.NO_NEW, collector._no_new_text())

    @staticmethod
    async def drain_media(collector):
        if collector.media is not None and collector._settings["download_media"]:
            try:
                await collector.media.process_pending()
                await collector.media.evict_if_needed()
            except Exception as e:  # noqa: BLE001
                log.debug("media caching skipped: %s", e)
