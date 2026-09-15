"""The collector's state vocabulary and tuning defaults.

Shared by `services/collector_service.py` (the facade),
`services/collector_tick.py` (the tick state machine) and the
`collector_*` collaborators, so none of them has to import each other
just to agree on what a state is called. Also owns `init_run_counters`:
the facade constructor's per-run counter block, moved here by Round G3
(RULE 16 §16.5 — the 40-method Collector must not grow, and the
constructor must fit the 30-LOC function budget).

The statuses are the vocabulary the feature request asked for:

    Collecting ...            work in progress
    Collected N ...           new lines were archived
    No new messages           the conversation is idle
    Not in private tab now    the active tab is a room, a group, or nothing
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional


class CollectorState:
    DISCONNECTED = "disconnected"
    OFF = "off"
    PAUSED = "paused"
    NOT_PRIVATE = "not_private"
    GROUP_TAB = "group_tab"
    BOOTSTRAPPING = "bootstrapping"
    COLLECTING = "collecting"
    COLLECTED = "collected"
    NO_NEW = "no_new"
    ERROR = "error"


IDLE_STATES = {CollectorState.DISCONNECTED, CollectorState.OFF,
               CollectorState.PAUSED, CollectorState.NOT_PRIVATE,
               CollectorState.GROUP_TAB, CollectorState.NO_NEW,
               CollectorState.ERROR}

DEFAULTS = {
    "enabled": True,
    "my_nick": "",
    "heartbeat_ms": 1500,
    "idle_heartbeat_ms": 5000,
    "throttle_factor": 4,
    "require_two_participants": True,
    "require_private": True,
    "chunk_size": 80,
    "chunk_pause_ms": 40,
    "download_media": True,
    "max_bootstrap": 0,          # 0 = no cap
    "auto_backfill": True,       # scroll to top once per person for full history
    "backfill_wait_s": 2.0,
}

MAX_PROBE_PENALTY = 4.0


# The Collector constructor's per-run counter block, moved here verbatim
# (Round G3): RULE 16 §16.5 forbids the 40-method class from growing a
# method and caps the constructor at 30 LOC, so the fresh-state recipe
# lives with the state vocabulary it initialises. The partial resets
# during a run are different sets for different moments and stay in the
# collaborators (collector_partner/report/tick).
def init_run_counters(host) -> None:
    """Set every per-run counter on ``host`` to its fresh start value."""
    host._state = CollectorState.DISCONNECTED
    host._text = ""
    host._nick = ""
    host._verified = False      # the two-step gate passed for _nick
    host._added = 0
    host._total = 0
    host._error = ""
    host._warning = ""
    host._agent = 0
    host._self_heals = 0
    host._throttled = False
    host._paused = False
    host._running = True
    host._probe_penalty = 1.0
    host._last_emitted: tuple = ()
    host._stop_event: Optional[asyncio.Event] = None
    host._busy = False
    host._force_backfill = False
    host._backfill_pending = False
    host._last_probe: dict = {}
    host._last_sync_reason = ""
    host._last_sync_added = 0
    host._last_sync_count = 0
    host._last_media_repaired = 0
    host._last_media_requeued = 0
    host._detected_my_nick = ""


@dataclass
class CollectorDeps:
    """The collaborators one `Collector` runs with (Round G step 4).

    The facade constructor takes this single value instead of seven
    keywords; `services/history/__init__.py` (the only production caller)
    and the tests build it at the call site.
    """

    cdp: Any = None
    repo: Any = None
    parser: Any = None
    media: Any = None
    settings: Optional[dict] = None
    lease: Any = None
    memory: Any = None


@dataclass(frozen=True, slots=True)
class TailSigs:
    """The four DOM signatures of one tick probe.

    `collector_tick.CollectorArchive` computes them once per tick and hands
    them to `maybe_rename` and `cursor_check` as one value (Round G step 4);
    the field names match `HistoryRepo.rename_if_same_conversation`'s.
    """

    head_sig: str = ""
    tail_sig: str = ""
    head_any: str = ""
    tail_any: str = ""


@dataclass(frozen=True, slots=True)
class TickIdent:
    """Whose conversation the tick archives: the partner and my own nick."""

    nick: str
    my_nick: str = ""
