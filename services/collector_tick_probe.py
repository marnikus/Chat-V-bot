"""Tick phases PROBE, GATE and NICK -- everything before a write.

Split out of `services/collector_tick` in round H (H3). This half reads the
page and decides whether the tab may be collected at all; it never touches
the archive. Every refusal path ends here, which is why the ARCHIVE half can
assume it was handed a tab that already passed all four gates.

The parser helpers (`_signature`, `verify_private`, `AGENT_VERSION`) are
injected by the host rather than imported, so `services/` gains no
`backend.*` import -- the same constraint the original module documented.

Imports point one way: `collector_tick` imports this; this imports only the
shared value types and `collector_service`.
"""

from __future__ import annotations

from typing import Optional

from services.collector_service import CollectorState
from services.collector_tick_types import Probe, Refusal


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
