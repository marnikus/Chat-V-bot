"""Collector status vocabulary and defaults."""


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


IDLE_STATES = {
    CollectorState.DISCONNECTED,
    CollectorState.OFF,
    CollectorState.PAUSED,
    CollectorState.NOT_PRIVATE,
    CollectorState.GROUP_TAB,
    CollectorState.NO_NEW,
    CollectorState.ERROR,
}

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
    "max_bootstrap": 0,  # 0 = no cap
    "auto_backfill": True,  # scroll to top once per person for full history
    "backfill_wait_s": 2.0,
}

MAX_PROBE_PENALTY = 4.0
