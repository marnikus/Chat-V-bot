"""The VERIFY and ARCHIVE phases of one collector tick (H-C5 split).

Round H step H-C5 took these out of `services/collector_tick.py` with the
probe phases. This half is where anything is written: the two-step
private-chat gate, the rename continuation, the person row, the cursor check,
backfill planning, the sync and the terminal status. Every collaborator
mutates the host `Collector` exactly where the old 212-LOC coroutine did, so
the emitted status payloads are byte-identical on every path.

Import direction: `services.collector_service` / `services.collector_states`
for the status constants and the tick values, `stores.history_requests` for
the pane signature; `verify_private` and `signature` are injected, so this
module adds no `backend.*` import.
"""


from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from services.collector_service import CollectorState  # noqa: E402
from services.collector_probe import Probe  # noqa: E402
from services.collector_states import TailSigs, TickIdent  # noqa: E402
from stores.history_requests import PaneSignature

log = logging.getLogger("chatbot")


@dataclass(frozen=True)
class Outcome:
    """The terminal (state, text) a tick reports."""
    state: str
    text: str


class SyncReportMixin:
    """The sync and the terminal status of one archive phase.

    Split out of `CollectorArchive` by Round H step H-C5 so neither class
    crosses the RULE 16 150-LOC cap. The seam is a real one: the walk below
    decides *whether* anything is archived, this mixin decides *what the tick
    reports afterwards* — the unchanged shortcut, the sync-counter writeback,
    the media drain, and the terminal `(state, text)` the UI shows.
    """

    async def unchanged(self, count: int) -> Outcome:
        """Idle conversation: NO_NEW, but the media downloader still runs.

        A backfill can re-queue dozens of rows and `process_pending` only
        takes 25 per pass, so the rest need the next tick even when nothing
        in the chat changed (Bug #2, 2026-09-07)."""
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
        """The sync tail: counters, media drains and the terminal status."""
        host = self._host
        self._apply_sync_counters(result)
        if result.media_repaired or result.media_requeued:
            host._last_media_repaired = int(result.media_repaired or 0)
            host._last_media_requeued = int(result.media_requeued or 0)
            host._log(f"Media recovery: repaired {result.media_repaired} "
                      f"message(s), re-queued {result.media_requeued} "
                      f"download(s)", "success", nick)
        await self._drain_media()
        return await self._terminal(result, nick)

    def _apply_sync_counters(self, result) -> None:
        """Copy the SyncResult counters onto the host status payload."""
        host = self._host
        host._backfill_pending = bool(result.backfill_pending)
        host._last_sync_reason = str(result.reason or "")
        host._last_sync_added = int(result.added or 0)
        host._last_sync_count = int(result.count or 0)
        host._added = result.added
        host._total = result.total

    async def _terminal(self, result, nick: str) -> Outcome:
        """COLLECTED / NOT_PRIVATE / NO_NEW — the final status of a tick."""
        host = self._host
        suffix = " (throttled — a run is active)" if host._throttled else ""
        if result.added:
            await host._notify_appended(nick, list(result.records[:200]),
                                        result.added, result.total)
            host._log(f"Archived {result.added} new message(s) "
                      f"(total {result.total})", "success", nick)
            text = (f"Collected {result.added} new "
                    f"message{'s' if result.added != 1 else ''} "
                    f"from {nick}{suffix}")
            state = host._set(CollectorState.COLLECTED, text)
            return Outcome(state, text)
        if not result.ok:
            host._log(f"Sync failed for “{nick}” ({result.reason})",
                      "error", nick)
            text = "Not in private tab now"
            state = host._set(CollectorState.NOT_PRIVATE, text)
            return Outcome(state, text)
        host._log(f"No new messages ({result.reason}, page count "
                  f"{result.count}, added {result.added})", "info", nick)
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
        except Exception as exc:                       # noqa: BLE001
            log.debug("media caching skipped: %s", exc)


class CollectorArchive(SyncReportMixin):
    """VERIFY + ARCHIVE: the private-chat gate, then the person row."""

    def __init__(self, host, signature, verify_private):
        self._host = host
        self._signature = signature
        self._verify_private = verify_private

    async def run(self, probe: Probe, nick: str, my_nick: str) -> Outcome:
        """Phase ARCHIVE: rename continuation → person rows → the two-step
        gate → cursor check / sync → terminal status."""
        host = self._host
        raw = probe.state
        sigs = TailSigs(head_sig=self._signature(raw.get("head")),
                        tail_sig=self._signature(raw.get("tail")),
                        head_any=self._signature(raw.get("head_any")),
                        tail_any=self._signature(raw.get("tail_any")))
        if host._nick and nick != host._nick:
            await self.maybe_rename(nick, probe, sigs)
        person_id = await self.open_person(nick, probe)
        refused = self.verify_gate(probe, nick)
        if refused is not None:
            return refused
        return await self.cursor_check(person_id, probe,
                                       TickIdent(nick, my_nick), sigs)

    async def maybe_rename(self, nick: str, probe: Probe,
                           sigs: TailSigs) -> None:
        host = self._host
        try:
            if await host.repo.rename_if_same_conversation(
                    host._nick, nick,
                    PaneSignature(sigs.head_sig, sigs.tail_sig,
                                  sigs.head_any, sigs.tail_any,
                                  probe.count),
                    pane_same=bool(probe.state.get("pane_same"))):
                host._log(f"Partner “{host._nick}” is now “{nick}” — "
                          "the history continues", "info", nick)
        except Exception as exc:                       # noqa: BLE001
            log.debug("rename check for %s failed: %s", nick, exc)

    async def open_person(self, nick: str, probe: Probe) -> int:
        """A verified private tab (active tab = private, 2 participants,
        title names the partner) is enough to create the person in BOTH
        stores. The author gate below protects the message rows from a
        mixed pane; the People row itself is safe even before that check
        passes."""
        host = self._host
        person_id = await host.repo.ensure_person(nick)
        remembered = await host._remember_partner(nick, probe.state)
        host._log(f"Partner “{nick}”: {remembered}", "info", nick)
        return person_id

    def verify_gate(self, probe: Probe, nick: str) -> Optional[Outcome]:
        """The two-step gate: refuse on failure, adopt `check.me` on pass."""
        host = self._host
        check = self._verify_private(probe.state, nick, host.my_nick)
        if not check.ok:
            host._nick = nick
            host._log(f"Private-chat gate refused “{nick}” ({check.reason})",
                      "warn", nick)
            state, text = host._gate_status(check, nick)
            host._refuse(state, text)
            return Outcome(state, text)
        host._verified = True
        if check.me and not host._detected_my_nick:
            host._detected_my_nick = check.me
        host._warning = ("" if host.my_nick else
                         "My Nick is not known yet — the archive will use "
                         "the single outbound author as 'me'")
        if nick != host._nick:
            host._nick = nick
            host._added = 0
        return None

    async def cursor_check(self, person_id: int, probe: Probe,
                           ident: TickIdent, sigs: TailSigs) -> Outcome:
        """Unchanged cursor → NO_NEW (media drains still run); otherwise
        plan the backfill, sync the conversation and finish."""
        host = self._host
        cursor = await host.repo.get_cursor(person_id)
        count = probe.count
        unchanged = (cursor["bootstrapped"] and count == cursor["dom_count"]
                     and sigs.tail_sig and sigs.tail_sig == cursor["tail_sig"]
                     and sigs.head_sig == cursor["head_sig"])
        person = await host.repo.get_person_by_id(person_id) or {}
        host._total = int(person.get("message_count") or 0)
        if unchanged:
            return await self.unchanged(count)
        bootstrap, want_backfill = self.plan_backfill(cursor)
        host._force_backfill = False
        host._set(CollectorState.BOOTSTRAPPING if bootstrap
                  else CollectorState.COLLECTING,
                  f"Collecting from {ident.nick}…")
        result = await host._sync(ident.nick, ident.my_nick, bootstrap,
                                  backfill_older=want_backfill)
        return await self.finish(result, ident.nick)

    def plan_backfill(self, cursor: dict) -> tuple[bool, bool]:
        """(bootstrap, want_backfill) — the scroll-to-top planning flags."""
        host = self._host
        bootstrap = not cursor["bootstrapped"]
        full_scan_complete = bool(cursor.get("full_scan_complete"))
        want_backfill = ((bool(host._settings.get("auto_backfill", True))
                          and not full_scan_complete
                          and not host._backfill_pending)
                         or host._force_backfill)
        return bootstrap, want_backfill
