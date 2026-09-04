"""Engine state machine transition tests."""
import pytest

from chatflow.core.models import EngineState as S
from chatflow.engine.state import StateMachine, can_transition


def test_happy_path():
    sm = StateMachine()
    assert sm.state == S.IDLE
    assert sm.go(S.CONNECTING) and sm.go(S.RUNNING)
    assert sm.go(S.PAUSED) and sm.go(S.RUNNING)
    assert sm.go(S.STOPPING) and sm.go(S.IDLE)


def test_illegal_transitions_rejected():
    sm = StateMachine()
    assert not can_transition(S.IDLE, S.RUNNING)
    assert not sm.go(S.RUNNING)
    assert sm.state == S.IDLE
    sm.go(S.CONNECTING)
    assert not sm.go(S.PAUSED)  # CONNECTING cannot go straight to PAUSED
    sm.force(S.RUNNING)
    assert not sm.go(S.IDLE)    # must go through STOPPING


def test_degraded_path():
    sm = StateMachine()
    sm.force(S.RUNNING)
    assert sm.go(S.DEGRADED)
    assert sm.go(S.RUNNING)     # reconnect ok


def test_error_recovery():
    sm = StateMachine()
    sm.force(S.ERROR)
    assert sm.go(S.CONNECTING)  # retry
    assert sm.go(S.IDLE)        # give up


def test_on_change_callback():
    seen = []
    sm = StateMachine(on_change=seen.append)
    sm.go(S.CONNECTING)
    sm.go(S.RUNNING)
    assert seen == ["CONNECTING", "RUNNING"]
