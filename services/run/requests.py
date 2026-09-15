"""The request/dependency values of the run family (Round G step 4).

`RunCoordinator` is constructed in exactly two shapes — the app bootstrap
wires it from the container, tests wire it from fakes — and both hold the
same seven collaborators. `StepContext` is the per-step triple the result
handler reads. One object per real consumer (the F5 rule); they live here
so the coordinator file (a §16.5 landmine) does not grow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RunDeps:
    """The collaborators one `RunCoordinator` runs with."""

    cdp: Any = None
    memory: Any = None
    criteria: Any = None
    bus: Any = None
    hooks: Any = None
    retry_policy: Any = None
    progress: Any = None


@dataclass(frozen=True, slots=True)
class StepContext:
    """Where one block execution sits in the run: who, which step, since when."""

    nick: str
    idx: int
    started: float
