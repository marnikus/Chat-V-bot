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

from services.collector_service import CollectorState  # noqa: E402,F401
from services.collector_tick_archive import CollectorArchive
from services.collector_tick_probe import CollectorProbe
from services.collector_tick_types import (                   # noqa: F401
    Outcome, PaneSignatures, Probe, Refusal, TickPhase,
)


class CollectorTick:
    """The state-machine shell: PROBE → GATE → NICK → VERIFY → ARCHIVE.

    Parser helpers are injected so this module adds no `backend.*` import:
    `signature` and `verify_private` come from `backend.chat_parser`
    (already imported by the host), `agent_version` from
    `backend.chat_agent_js`.
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
