from __future__ import annotations

from enum import Enum


class RunState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"
    DONE = "done"


_ALLOWED = {
    # A pause may be requested before Run; mark_running clears it.
    RunState.IDLE: {RunState.RUNNING, RunState.PAUSED},
    RunState.RUNNING: {RunState.PAUSED, RunState.STOPPING,
                       RunState.ERROR, RunState.DONE},
    RunState.PAUSED: {RunState.RUNNING, RunState.STOPPING, RunState.ERROR},
    RunState.STOPPING: {RunState.DONE, RunState.ERROR, RunState.IDLE},
    RunState.ERROR: {RunState.IDLE, RunState.RUNNING},
    RunState.DONE: {RunState.IDLE, RunState.RUNNING},
}


class RunStateMachine:
    def __init__(self) -> None:
        self.state = RunState.IDLE

    def transition(self, target: RunState | str) -> RunState:
        target = RunState(target)
        if target == self.state:
            return self.state
        if target not in _ALLOWED[self.state]:
            raise ValueError(f"invalid transition: {self.state.value} -> {target.value}")
        self.state = target
        return self.state

    def reset(self) -> RunState:
        self.state = RunState.IDLE
        return self.state

    def mark_running(self) -> RunState:
        if self.state in (RunState.ERROR, RunState.DONE):
            self.reset()
        return self.transition(RunState.RUNNING)

    def mark_paused(self) -> RunState:
        return self.transition(RunState.PAUSED)

    def mark_resumed(self) -> RunState:
        return self.transition(RunState.RUNNING)

    def mark_stopping(self) -> RunState:
        if self.state in (RunState.RUNNING, RunState.PAUSED):
            return self.transition(RunState.STOPPING)
        return self.state

    def mark_error(self) -> RunState:
        if self.state == RunState.IDLE:
            self.state = RunState.ERROR
            return self.state
        return self.transition(RunState.ERROR)

    def mark_done(self) -> RunState:
        if self.state in (RunState.RUNNING, RunState.STOPPING):
            return self.transition(RunState.DONE)
        return self.state
