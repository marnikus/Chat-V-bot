"""The request/dependency values of the run family (Round G step 4).

`RunCoordinator` is constructed in exactly two shapes — the app bootstrap
wires it from the container, tests wire it from fakes — and both hold the
same seven collaborators. `StepContext` is the per-step triple the result
handler reads. One object per real consumer (the F5 rule); they live here
so the coordinator file (a §16.5 landmine) does not grow.

`UserRecord` is bound here too — it is the one value the whole run ladder
constructs (a standalone cycle, a single-target cycle, a queue row), and
having one binding instead of one per file is what keeps
`services.run.progress.UserRecord` identical to `stores.user_memory.UserRecord`
(the P0-2 pin) without three copies of the import guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from stores.user_memory import UserRecord
except Exception:
    @dataclass
    class UserRecord:
        nick: str
        messaged: bool = False


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
