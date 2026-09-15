"""The `Collector._tick` state machine — facade over probe + archive (H-C4).

Original 425 LOC split into two ≤200 LOC helpers named by responsibility:
collector_probe.py (PROBE/GATE/NICK) and collector_archive.py (ARCHIVE).
This file keeps the state-machine shell.

Design: AREA_C H-C4 — helper extraction by named responsibility.
"""

from __future__ import annotations

import logging
from enum import Enum

from services.collector_archive import CollectorArchive, Outcome
from services.collector_probe import CollectorProbe, Probe, Refusal
from services.collector_service import CollectorState

log = logging.getLogger("chatbot")


class TickPhase(str, Enum):
    """Phases one tick walks: PROBE → GATE → NICK → VERIFY → ARCHIVE."""

    PROBE = "probe"
    GATE = "gate"
    NICK = "nick"
    VERIFY = "verify"
    ARCHIVE = "archive"
    TERMINAL = "terminal"


class CollectorTick:
    """State-machine shell: PROBE → GATE → NICK → VERIFY → ARCHIVE."""

    def __init__(self, host, *, signature, verify_private, agent_version):
        self._host = host
        self._probe = CollectorProbe(host, agent_version)
        self._archive = CollectorArchive(host, signature, verify_private)

    async def run(self) -> tuple[str, str]:
        host = self._host
        probe = await self._probe.inspect()
        refusal = self._probe.refuse_tab(probe)
        if refusal is not None:
            host._refuse(refusal.state, refusal.text)
            return refusal.state, refusal.text
        nick = probe.partner_nick
        my_nick = self._probe.adopt_my_nick(probe)
        if my_nick and nick.lower() == my_nick.lower():
            host._log("Partner is the same as My Nick — refusing", "warn", nick)
            host._refuse(CollectorState.NOT_PRIVATE, "Partner is ambiguous (same as My Nick)")
            return (CollectorState.NOT_PRIVATE, "Partner is ambiguous (same as My Nick)")
        outcome = await self._archive.run(probe, nick, my_nick)
        return outcome.state, outcome.text


# Re-export for backward compat (tests import from collector_tick)
__all__ = ["CollectorTick", "CollectorProbe", "CollectorArchive", "Probe", "Refusal", "Outcome", "TickPhase"]
