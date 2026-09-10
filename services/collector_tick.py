"""The `Collector._tick` state machine (AREA C extraction).

The 212-LOC heartbeat coroutine is split into the five phases it always
implicitly ran, each owned by a small collaborator with CC ≤ 10:

    TickPhase.PROBE   — in-page agent check (self-heal) + the probe payload
    TickPhase.GATE    — the four "refuse this tab" gates
    TickPhase.NICK    — My-Nick detection and stale-nick adoption
    TickPhase.VERIFY  — the two-step private-chat gate
    TickPhase.ARCHIVE — rename continuation, person rows, cursor check,
                        backfill planning, sync and the terminal status

Every collaborator mutates the host `Collector` exactly where the old
coroutine did, so the emitted status payloads are byte-identical on every
path. The parser helpers (`_signature`, `verify_private`,
`chat_agent_js.AGENT_VERSION`) are injected by `Collector._tick` so this
module keeps `services/` free of new `backend.*` imports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

log = logging.getLogger("chatbot")

from services.collector_service import CollectorState  # noqa: E402


class TickPhase(str, Enum):
    """The phases one tick walks: PROBE → GATE → NICK → VERIFY → ARCHIVE."""
    PROBE = "probe"
    GATE = "gate"
    NICK = "nick"
    VERIFY = "verify"
    ARCHIVE = "archive"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class Refusal:
    """A terminal refusal: the tick ends without touching the archive."""
    state: str
    text: str


@dataclass(frozen=True)
class Outcome:
    """The terminal (state, text) a tick reports."""
    state: str
    text: str


@dataclass(frozen=True)
class Probe:
    """What the page reported this tick (after the optional self-heal)."""
    state: dict
    agent: int = 0
    self_healed: bool = False

    @property
    def count(self) -> int:
        return int(self.state.get("count") or 0)

    @property
    def partner_nick(self) -> str:
        return " ".join(str(self.state.get("partner") or "").split()).strip()

    @property
    def me_nick(self) -> str:
        return " ".join(str(self.state.get("me") or "").split()).strip()

    @property
    def out_authors(self) -> list[str]:
        return [str(o or "").strip() for o in
                (self.state.get("out_authors") or [])]


class CollectorProbe:
    """Phases PROBE / GATE / NICK (read-only page state + nick adoption)."""

    def __init__(self, host, agent_version: int):
        self._host = host
        self._agent_version = agent_version

    async def inspect(self) -> Probe:
        """Read the page state; self-heal a stale or missing in-page agent."""
        host = self._host
        state = await host.parser.state()
        self_healed = False
        if int(state.get("agent") or 0) < self._agent_version:
            # No agent, or one that predates the pane-scoped parser: an old
            # agent cannot tell us who wrote what, so it may not be trusted.
            await host.parser.install()
            host._self_heals += 1
            state = await host.parser.state()
            self_healed = True
            host._log(f"Re-installed the in-page agent "
                      f"(v{int(state.get('agent') or 0)})", "info")
        host._agent = int(state.get("agent") or 0)
        host._error = ""
        host._last_probe = self._probe_payload(state)
        return Probe(state=state, agent=host._agent, self_healed=self_healed)

    @staticmethod
    def _probe_payload(state: dict) -> dict:
        """The `last_probe` summary shown in the Radar window."""
        return {
            "count": int(state.get("count") or 0),
            "panes": int(state.get("panes") or 0),
            "pane_source": str(state.get("pane_source") or ""),
            "participants": int(state.get("participants") or 0),
            "partner": str(state.get("partner") or ""),
            "in_authors": list(state.get("in_authors") or []),
            "out_authors": list(state.get("out_authors") or []),
            "scroll": dict(state.get("scroll") or {}),
        }

    def refuse_tab(self, probe: Probe) -> Optional[Refusal]:
        """The four "not a private tab" gates (ok / tab / participants / nick)."""
        host = self._host
        state = probe.state
        if not state.get("ok", True):
            host._log("No chat on this page (state not ok)", "warn")
            return Refusal(CollectorState.NOT_PRIVATE,
                           "Not in private tab now")
        if state.get("tab") != "private":
            host._log(f"Active tab is “{state.get('tab')}”, not private —",
                      "warn", state.get("me") or "")
            return Refusal(CollectorState.NOT_PRIVATE,
                           "Not in private tab now")
        refusal = self._participants_refusal(host, state)
        if refusal is not None:
            return refusal
        nick = probe.partner_nick
        if not nick:
            host._log("No partner nick in the active tab", "warn")
            return Refusal(CollectorState.NOT_PRIVATE,
                           "Not in private tab now")
        return None

    @staticmethod
    def _participants_refusal(host, state: dict) -> Optional[Refusal]:
        """The GROUP_TAB gate. "Exactly two people" is enforced whenever
        the page exposes a count. A private pane WITHOUT a readable counter
        — the partner with no avatar identification (2026-09-08) — falls
        through to the author gate below, which refuses the chat the moment
        any third nick writes here. No gender/avatar check belongs in this
        path: filters only govern auto-detection in the Action block."""
        participants = int(state.get("participants") or 0)
        if (host._settings["require_two_participants"]
                and participants > 0 and participants != 2):
            host._log(f"Refused: {participants} participants, not a private "
                      "chat", "warn", state.get("partner") or "")
            return Refusal(
                CollectorState.GROUP_TAB,
                f"Group tab ({participants} people) — not collected")
        return None

    def adopt_my_nick(self, probe: Probe) -> str:
        """Detect / adopt My Nick; replace a saved nick that went stale."""
        host = self._host
        nick = probe.partner_nick
        # My Nick is optional for the archive: in a verified two-person chat
        # the single outbound author IS me, so we adopt it for this session
        # (it is not persisted to config.json unless the user saves it).
        detected_me = probe.me_nick or self._single_out_author(
            probe.out_authors, nick)
        if not host.my_nick and detected_me:
            host.configure(my_nick=detected_me)
            host._detected_my_nick = detected_me
            host._log(f"Detected My Nick as “{detected_me}”", "info", nick)
        elif self._saved_nick_stale(host, detected_me, probe.out_authors):
            # A saved My Nick can go stale: the user renames themselves on
            # the site, and from then on every tick would refuse the chat
            # because the pane's outbound author looks like a "stranger".
            # When the pane self-reports a DIFFERENT nick and the configured
            # one is not among the outbound authors, the pane wins for this
            # session (bug report 2026-09-08, "user now uses a diff name").
            previous = host.my_nick
            host.configure(my_nick=detected_me)
            host._detected_my_nick = detected_me
            host._log(f"My Nick changed from “{previous}” to "
                      f"“{detected_me}” — adopted from the page", "info",
                      nick)
        return host.my_nick or detected_me

    @staticmethod
    def _single_out_author(outs: list, nick: str) -> str:
        """The one outbound author (when the page does not name `me`)."""
        singles = [o for o in outs if o]
        if len(singles) == 1 and singles[0].lower() != nick.lower():
            return singles[0]
        return ""

    @staticmethod
    def _saved_nick_stale(host, detected_me: str, outs: list) -> bool:
        return (bool(host.my_nick) and bool(detected_me)
                and detected_me.lower() != host.my_nick.lower()
                and host.my_nick.lower() not in
                {o.lower() for o in outs if o})


class CollectorArchive:
    """Phase ARCHIVE (the write half of one tick)."""

    def __init__(self, host, signature, verify_private):
        self._host = host
        self._signature = signature
        self._verify_private = verify_private

    async def run(self, probe: Probe, nick: str, my_nick: str) -> Outcome:
        """Phase ARCHIVE: rename continuation → person rows → the two-step
        gate → cursor check / sync → terminal status."""
        host = self._host
        raw = probe.state
        head_sig = self._signature(raw.get("head"))
        tail_sig = self._signature(raw.get("tail"))
        head_any = self._signature(raw.get("head_any"))
        tail_any = self._signature(raw.get("tail_any"))
        if host._nick and nick != host._nick:
            await self.maybe_rename(nick, probe, head_sig, tail_sig,
                                    head_any, tail_any)
        person_id = await self.open_person(nick, probe)
        refused = self.verify_gate(probe, nick)
        if refused is not None:
            return refused
        return await self.cursor_check(person_id, probe, nick, my_nick,
                                       head_sig, tail_sig)

    async def maybe_rename(self, nick: str, probe: Probe, head_sig: str,
                           tail_sig: str, head_any: str,
                           tail_any: str) -> None:
        host = self._host
        try:
            if await host.repo.rename_if_same_conversation(
                    host._nick, nick, head_sig, tail_sig,
                    head_any=head_any, tail_any=tail_any,
                    dom_count=probe.count,
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

    async def cursor_check(self, person_id: int, probe: Probe, nick: str,
                           my_nick: str, head_sig: str,
                           tail_sig: str) -> Outcome:
        """Unchanged cursor → NO_NEW (media drains still run); otherwise
        plan the backfill, sync the conversation and finish."""
        host = self._host
        cursor = await host.repo.get_cursor(person_id)
        count = probe.count
        unchanged = (cursor["bootstrapped"] and count == cursor["dom_count"]
                     and tail_sig and tail_sig == cursor["tail_sig"]
                     and head_sig == cursor["head_sig"])
        person = await host.repo.get_person_by_id(person_id) or {}
        host._total = int(person.get("message_count") or 0)
        if unchanged:
            return await self.unchanged(count)
        bootstrap, want_backfill = self.plan_backfill(cursor)
        host._force_backfill = False
        host._set(CollectorState.BOOTSTRAPPING if bootstrap
                  else CollectorState.COLLECTING,
                  f"Collecting from {nick}…")
        result = await host._sync(nick, my_nick, bootstrap,
                                  backfill_older=want_backfill)
        return await self.finish(result, nick)

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


class CollectorTick:
    """The state-machine shell: PROBE → GATE → NICK → VERIFY → ARCHIVE.

    Parser helpers are injected so this module adds no `backend.*` import:
    `signature` and `verify_private` come from `backend.chat_parser`
    (already imported by the host), `agent_version` from
    `core.chat_agent_js`.
    """

    def __init__(self, host, *, signature, verify_private, agent_version):
        self._host = host
        self._probe = CollectorProbe(host, agent_version)
        self._archive = CollectorArchive(host, signature, verify_private)

    async def run(self) -> tuple[str, str]:
        """Walk one tick; every terminal path returns `(state, text)`."""
        host = self._host
        probe = await self._probe.inspect()            # TickPhase.PROBE
        refusal = self._probe.refuse_tab(probe)        # TickPhase.GATE
        if refusal is not None:
            host._refuse(refusal.state, refusal.text)
            return refusal.state, refusal.text
        nick = probe.partner_nick
        my_nick = self._probe.adopt_my_nick(probe)     # TickPhase.NICK
        if my_nick and nick.lower() == my_nick.lower():
            host._log("Partner is the same as My Nick — refusing", "warn",
                      nick)
            host._refuse(CollectorState.NOT_PRIVATE,
                         "Partner is ambiguous (same as My Nick)")
            return (CollectorState.NOT_PRIVATE,
                    "Partner is ambiguous (same as My Nick)")
        outcome = await self._archive.run(probe, nick, my_nick)  # VERIFY+ARCHIVE
        return outcome.state, outcome.text
