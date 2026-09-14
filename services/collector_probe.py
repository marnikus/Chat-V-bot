"""Collector probe phases — extracted from collector_tick (H-C4).

Phases PROBE / GATE / NICK (read-only page state + nick adoption).

Design: AREA_C H-C4 — helper named by responsibility, ≤200 LOC.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from services.collector_service import CollectorState

log = logging.getLogger("chatbot")


@dataclass(frozen=True)
class Refusal:
    state: str
    text: str


@dataclass(frozen=True)
class Probe:
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
        return [str(o or "").strip() for o in (self.state.get("out_authors") or [])]


class CollectorProbe:
    """Phases PROBE / GATE / NICK (read-only page state + nick adoption)."""

    def __init__(self, host, agent_version: int):
        self._host = host
        self._agent_version = agent_version

    async def inspect(self) -> Probe:
        host = self._host
        state = await host.parser.state()
        self_healed = False
        if int(state.get("agent") or 0) < self._agent_version:
            await host.parser.install()
            host._self_heals += 1
            state = await host.parser.state()
            self_healed = True
            host._log(f"Re-installed the in-page agent (v{int(state.get('agent') or 0)})", "info")
        host._agent = int(state.get("agent") or 0)
        host._error = ""
        host._last_probe = self._probe_payload(state)
        return Probe(state=state, agent=host._agent, self_healed=self_healed)

    @staticmethod
    def _probe_payload(state: dict) -> dict:
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
        host = self._host
        state = probe.state
        if not state.get("ok", True):
            host._log("No chat on this page (state not ok)", "warn")
            return Refusal(CollectorState.NOT_PRIVATE, "Not in private tab now")
        if state.get("tab") != "private":
            host._log(f"Active tab is “{state.get('tab')}”, not private —", "warn", state.get("me") or "")
            return Refusal(CollectorState.NOT_PRIVATE, "Not in private tab now")
        refusal = self._participants_refusal(host, state)
        if refusal is not None:
            return refusal
        nick = probe.partner_nick
        if not nick:
            host._log("No partner nick in the active tab", "warn")
            return Refusal(CollectorState.NOT_PRIVATE, "Not in private tab now")
        return None

    @staticmethod
    def _participants_refusal(host, state: dict) -> Optional[Refusal]:
        participants = int(state.get("participants") or 0)
        if host._settings["require_two_participants"] and participants > 0 and participants != 2:
            host._log(
                f"Refused: {participants} participants, not a private chat", "warn", state.get("partner") or ""
            )
            return Refusal(CollectorState.GROUP_TAB, f"Group tab ({participants} people) — not collected")
        return None

    def adopt_my_nick(self, probe: Probe) -> str:
        host = self._host
        nick = probe.partner_nick
        detected_me = probe.me_nick or self._single_out_author(probe.out_authors, nick)
        if not host.my_nick and detected_me:
            host.configure(my_nick=detected_me)
            host._detected_my_nick = detected_me
            host._log(f"Detected My Nick as “{detected_me}”", "info", nick)
        elif self._saved_nick_stale(host, detected_me, probe.out_authors):
            previous = host.my_nick
            host.configure(my_nick=detected_me)
            host._detected_my_nick = detected_me
            host._log(f"My Nick changed from “{previous}” to “{detected_me}” — adopted from the page", "info", nick)
        return host.my_nick or detected_me

    @staticmethod
    def _single_out_author(outs: list, nick: str) -> str:
        singles = [o for o in outs if o]
        if len(singles) == 1 and singles[0].lower() != nick.lower():
            return singles[0]
        return ""

    @staticmethod
    def _saved_nick_stale(host, detected_me: str, outs: list) -> bool:
        return (
            bool(host.my_nick)
            and bool(detected_me)
            and detected_me.lower() != host.my_nick.lower()
            and host.my_nick.lower() not in {o.lower() for o in outs if o}
        )
