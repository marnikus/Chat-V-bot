"""The wiring bundles of the world-bound services (Round G step 4).

`UndoService`, `PeopleService` and `restart_world` all take the same kind of
input: the collaborators of the current world. Each keeps its own bundle —
one object per real consumer, the F5 rule — but the three live in one module
because they change together: when the app grows a new world-bound surface,
every bundle here is revisited at once. `None` always means "not wired yet",
and `attach()` replaces only the fields that are set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from core.events import EventBus


@dataclass
class UndoDeps:
    """The collaborators `UndoService` runs with."""

    archive: Any = None
    people: Any = None
    labels: Any = None
    dbs: Any = None
    memory: Any = None
    engine: Any = None
    #: None falls back to a fresh `EventBus()` at construction.
    bus: Optional[EventBus] = None


@dataclass
class PeopleDeps:
    """The collaborators `PeopleService` runs with."""

    memory: Any = None
    engine: Any = None
    labels: Any = None
    undo: Any = None
    bus: Optional[EventBus] = None


@dataclass
class RestartDeps:
    """What `restart_world` rebuilds the world-bound surfaces from.

    `archive` None means the world is gone — the restart is a no-op.
    `bus` must be set for any real restart.
    """

    memory: Any = None
    archive: Any = None
    labels: Any = None
    undo: Any = None
    bus: Optional[EventBus] = None
