"""Collector archive phase — extracted from collector_tick (H-C4).

Phase ARCHIVE (write half of one tick): rename, person rows, gate, cursor,
backfill planning, sync and terminal status.

Design: AREA_C H-C4 — helper named by responsibility, ≤200 LOC.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from services.collector_service import CollectorState
from services.collector_states import TailSigs, TickIdent
from stores.history_requests import PaneSignature

log = logging.getLogger("chatbot")


@dataclass(frozen=True)
class Outcome:
    state: str
    text: str


class CollectorArchive:
    """Phase ARCHIVE (the write half of one tick)."""

    def __init__(self, host, signature, verify_private):
        self._host = host
        self._signature = signature
        self._verify_private = verify_private

    async def run(self, probe, nick: str, my_nick: str) -> Outcome:
        host = self._host
        raw = probe.state
        sigs = TailSigs(
            head_sig=self._signature(raw.get("head")),
            tail_sig=self._signature(raw.get("tail")),
            head_any=self._signature(raw.get("head_any")),
            tail_any=self._signature(raw.get("tail_any")),
        )
        if host._nick and nick != host._nick:
            await self.maybe_rename(nick, probe, sigs)
        person_id = await self.open_person(nick, probe)
        refused = self.verify_gate(probe, nick)
        if refused is not None:
            return refused
        return await self.cursor_check(person_id, probe, TickIdent(nick, my_nick), sigs)

    async def maybe_rename(self, nick: str, probe, sigs: TailSigs) -> None:
        host = self._host
        try:
            if await host.repo.rename_if_same_conversation(
                host._nick,
                nick,
                PaneSignature(sigs.head_sig, sigs.tail_sig, sigs.head_any, sigs.tail_any, probe.count),
                pane_same=bool(probe.state.get("pane_same")),
            ):
                host._log(f"Partner “{host._nick}” is now “{nick}” — the history continues", "info", nick)
        except Exception as exc:  # noqa: BLE001
            log.debug("rename check for %s failed: %s", nick, exc)

    async def open_person(self, nick: str, probe) -> int:
        host = self._host
        person_id = await host.repo.ensure_person(nick)
        remembered = await host._remember_partner(nick, probe.state)
        host._log(f"Partner “{nick}”: {remembered}", "info", nick)
        return person_id

    def verify_gate(self, probe, nick: str) -> Optional[Outcome]:
        host = self._host
        check = self._verify_private(probe.state, nick, host.my_nick)
        if not check.ok:
            host._nick = nick
            host._log(f"Private-chat gate refused “{nick}” ({check.reason})", "warn", nick)
            state, text = host._gate_status(check, nick)
            host._refuse(state, text)
            return Outcome(state, text)
        host._verified = True
        if check.me and not host._detected_my_nick:
            host._detected_my_nick = check.me
        host._warning = (
            "" if host.my_nick else "My Nick is not known yet — the archive will use the single outbound author as 'me'"
        )
        if nick != host._nick:
            host._nick = nick
            host._added = 0
        return None

    async def cursor_check(self, person_id: int, probe, ident: TickIdent, sigs: TailSigs) -> Outcome:
        host = self._host
        cursor = await host.repo.get_cursor(person_id)
        count = probe.count
        unchanged = (
            cursor["bootstrapped"]
            and count == cursor["dom_count"]
            and sigs.tail_sig
            and sigs.tail_sig == cursor["tail_sig"]
            and sigs.head_sig == cursor["head_sig"]
        )
        person = await host.repo.get_person_by_id(person_id) or {}
        host._total = int(person.get("message_count") or 0)
        if unchanged:
            return await self.unchanged(count)
        bootstrap, want_backfill = self.plan_backfill(cursor)
        host._force_backfill = False
        host._set(
            CollectorState.BOOTSTRAPPING if bootstrap else CollectorState.COLLECTING, f"Collecting from {ident.nick}…"
        )
        result = await host._sync(ident.nick, ident.my_nick, bootstrap, backfill_older=want_backfill)
        return await self.finish(result, ident.nick)

    def plan_backfill(self, cursor: dict) -> tuple[bool, bool]:
        host = self._host
        bootstrap = not cursor["bootstrapped"]
        full_scan_complete = bool(cursor.get("full_scan_complete"))
        want_backfill = (
            (bool(host._settings.get("auto_backfill", True)) and not full_scan_complete and not host._backfill_pending)
            or host._force_backfill
        )
        return bootstrap, want_backfill

    async def unchanged(self, count: int) -> Outcome:
        host = self._host
        host._added = 0
        host._last_sync_reason = "unchanged_cursor"
        host._last_sync_added = 0
        host._last_sync_count = count
        await self._drain_media()
        text = host._no_new_text()
        state = host._set(CollectorState.NO_NEW, text)
        return Outcome(state, text)

    async def finish(self, result, nick: str) -> Outcome:
        host = self._host
        self._apply_sync_counters(result)
        if result.media_repaired or result.media_requeued:
            host._last_media_repaired = int(result.media_repaired or 0)
            host._last_media_requeued = int(result.media_requeued or 0)
            host._log(
                f"Media recovery: repaired {result.media_repaired} message(s), re-queued {result.media_requeued} download(s)",
                "success",
                nick,
            )
        await self._drain_media()
        return await self._terminal(result, nick)

    def _apply_sync_counters(self, result) -> None:
        host = self._host
        host._backfill_pending = bool(result.backfill_pending)
        host._last_sync_reason = str(result.reason or "")
        host._last_sync_added = int(result.added or 0)
        host._last_sync_count = int(result.count or 0)
        host._added = result.added
        host._total = result.total

    async def _terminal(self, result, nick: str) -> Outcome:
        host = self._host
        suffix = " (throttled — a run is active)" if host._throttled else ""
        if result.added:
            await host._notify_appended(nick, list(result.records[:200]), result.added, result.total)
            host._log(f"Archived {result.added} new message(s) (total {result.total})", "success", nick)
            text = f"Collected {result.added} new message{'s' if result.added != 1 else ''} from {nick}{suffix}"
            state = host._set(CollectorState.COLLECTED, text)
            return Outcome(state, text)
        if not result.ok:
            host._log(f"Sync failed for “{nick}” ({result.reason})", "error", nick)
            text = "Not in private tab now"
            state = host._set(CollectorState.NOT_PRIVATE, text)
            return Outcome(state, text)
        host._log(f"No new messages ({result.reason}, page count {result.count}, added {result.added})", "info", nick)
        text = host._no_new_text()
        state = host._set(CollectorState.NO_NEW, text)
        return Outcome(state, text)

    async def _drain_media(self) -> None:
        host = self._host
        if host.media is None or not host._settings["download_media"]:
            return
        try:
            await host.media.process_pending()
            await host.media.evict_if_needed()
        except Exception as exc:  # noqa: BLE001
            log.debug("media caching skipped: %s", exc)
