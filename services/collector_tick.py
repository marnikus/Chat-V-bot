"""The `Collector._tick` state machine (AREA C extraction).

The 212-LOC heartbeat coroutine is split into the five phases it always
implicitly ran, each owned by a small collaborator with CC ≤ 10. Round H step
H-C5 gave the two halves of that walk their own modules, leaving here the
phase vocabulary and the shell that walks it:

    TickPhase               PROBE → GATE → NICK → VERIFY → ARCHIVE
    collector_probe.py      CollectorProbe   PROBE, GATE, NICK
    collector_archive.py    CollectorArchive VERIFY, ARCHIVE

Every collaborator mutates the host `Collector` exactly where the old
coroutine did, so the emitted status payloads are byte-identical on every
path. The parser helpers (`_signature`, `verify_private`,
`chat_agent_js.AGENT_VERSION`) are injected by `Collector._tick` so this
family keeps `services/` free of new `backend.*` imports.

`Probe`, `Refusal`, `Outcome`, `CollectorProbe` and `CollectorArchive` are
re-exported from here because `services/collector_states.py`, the collector
structure gate and the phase tests all name this module as the tick's home.
"""

from __future__ import annotations

from enum import Enum

from services.collector_service import CollectorState  # noqa: E402
from services.collector_archive import CollectorArchive, Outcome  # noqa: F401
from services.collector_probe import CollectorProbe, Probe, Refusal  # noqa: F401

__all__ = ["CollectorArchive", "CollectorProbe", "CollectorTick", "Outcome",
           "Probe", "Refusal", "TickPhase"]


class TickPhase(str, Enum):
    """The phases one tick walks: PROBE → GATE → NICK → VERIFY → ARCHIVE."""
    PROBE = "probe"
    GATE = "gate"
    NICK = "nick"
    VERIFY = "verify"
    ARCHIVE = "archive"
    TERMINAL = "terminal"


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
