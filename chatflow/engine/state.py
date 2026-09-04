"""Engine state machine (pure transition table + guarded holder)."""
from __future__ import annotations

from ..core.models import EngineState as S

ALLOWED: dict[S, frozenset[S]] = {
    S.IDLE: frozenset({S.CONNECTING, S.ERROR}),
    S.CONNECTING: frozenset({S.RUNNING, S.IDLE, S.ERROR}),
    S.RUNNING: frozenset({S.PAUSED, S.STOPPING, S.DEGRADED, S.ERROR}),
    S.PAUSED: frozenset({S.RUNNING, S.STOPPING, S.DEGRADED, S.ERROR}),
    S.STOPPING: frozenset({S.IDLE, S.ERROR}),
    S.DEGRADED: frozenset({S.RUNNING, S.STOPPING, S.IDLE, S.ERROR}),
    S.ERROR: frozenset({S.IDLE, S.CONNECTING}),
}


def can_transition(cur: S, nxt: S) -> bool:
    return nxt in ALLOWED.get(cur, frozenset())


class StateMachine:
    def __init__(self, initial: S = S.IDLE, on_change=None):
        self._state = initial
        self._on_change = on_change

    @property
    def state(self) -> S:
        return self._state

    def go(self, nxt: S) -> bool:
        """Attempt a transition; no-op (False) when not allowed."""
        if nxt == self._state or not can_transition(self._state, nxt):
            return False
        self._state = nxt
        if self._on_change:
            self._on_change(nxt.value)
        return True

    def force(self, nxt: S) -> None:
        self._state = nxt
        if self._on_change:
            self._on_change(nxt.value)
