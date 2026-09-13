"""The collector's state vocabulary and tuning defaults.

Pure data, shared by `services/collector_service.py` (the facade),
`services/collector_tick.py` (the tick state machine) and the
`collector_*` collaborators, so none of them has to import each other
just to agree on what a state is called.

The statuses are the vocabulary the feature request asked for:

    Collecting ...            work in progress
    Collected N ...           new lines were archived
    No new messages           the conversation is idle
    Not in private tab now    the active tab is a room, a group, or nothing
"""

from __future__ import annotations


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
