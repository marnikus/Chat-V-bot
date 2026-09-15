"""BridgeContext — the shared dependencies every domain bridge reads.

The Router exposes the historical private attribute names (`_config`,
`_memory`, `_engine`, …) as write-through properties onto ONE context
object, so hand-assembled bridges in tests (`Bridge.__new__` + manual
attribute injection) keep working: assigning `br._config = cfg` updates
the context, and every lazily-built service or bridge sees it.

Services are constructed lazily on first use (a `__new__`-assembled
router may have its dependencies set in any order) and re-attached when
a dependency is replaced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from core.events import EventBus
from services.cdp_service import CdpService
from services.people_service import PeopleDeps, PeopleService
from services.undo_service import UndoDeps, UndoService


@dataclass(eq=False, repr=False)
class BridgeContext:
    """Shared, mutable wiring state for the bridge layer.

    The constructor is synthesized (Round G step 4): the fields are the old
    ten ctor parameters verbatim, in their old order, every one defaulting
    to None. `__post_init__` does exactly what the hand-written body did —
    the bus fallback and the three lazy service slots — and `eq=False,
    repr=False` keep identity comparison, so nothing downstream changes.
    """

    cdp: Any = None
    memory: Any = None
    criteria: Any = None
    engine: Any = None
    config: Any = None
    presets: Any = None
    labels: Any = None              # LabelStore (lazily built if None)
    dbs: Any = None                 # DbManager (lazily built if None)
    archive: Any = None             # HistoryService (attach_history)
    bus: Optional[EventBus] = None

    def __post_init__(self):
        self.bus = self.bus or EventBus()
        # lazily-built services
        self._people_svc: Optional[PeopleService] = None
        self._undo_svc: Optional[UndoService] = None
        self._cdp_svc: Optional[CdpService] = None

    # ── lazily-built label store / db manager (tests rely on this) ─
    def label_store(self):
        if self.labels is None:
            from stores.label_store import LabelStore
            self.labels = LabelStore(self.config)
            self.sync_services()
        return self.labels

    def db_manager(self):
        if self.dbs is None:
            from services.db_service import DbManager
            self.dbs = DbManager(config=self.config)
            self.sync_services()
        return self.dbs

    # ── lazily-built services ────────────────────────────────────
    def _build_people(self) -> PeopleService:
        self._people_svc = PeopleService(PeopleDeps(
            memory=self.memory, engine=self.engine,
            labels=self.labels, undo=self._undo_svc, bus=self.bus))
        return self._people_svc

    def _build_undo(self) -> UndoService:
        self._undo_svc = UndoService(self.config, UndoDeps(
            archive=self.archive, people=self._people_svc,
            labels=self.labels, dbs=self.dbs, memory=self.memory,
            engine=self.engine, bus=self.bus))
        return self._undo_svc

    def _crosswire(self) -> None:
        """People pushes undo entries; undo reverses people entries —
        whichever service was built first captured a None for the other,
        so both refs are patched here after either build."""
        if self._people_svc is not None and self._undo_svc is not None:
            self._people_svc.attach(PeopleDeps(undo=self._undo_svc))
            self._undo_svc.attach(UndoDeps(people=self._people_svc))

    @property
    def people(self) -> PeopleService:
        if self._people_svc is None:
            self._build_people()
        if self._undo_svc is None:
            self._build_undo()
        self._crosswire()
        return self._people_svc

    @property
    def undo(self) -> UndoService:
        if self._undo_svc is None:
            self._build_undo()
        if self._people_svc is None:
            self._build_people()
        self._crosswire()
        return self._undo_svc

    @property
    def cdp_service(self) -> CdpService:
        if self._cdp_svc is None:
            self._cdp_svc = CdpService(cdp=self.cdp, bus=self.bus)
            self._cdp_svc.install_status_forwarding()
        return self._cdp_svc

    # ── dependency replacement keeps built services in sync ──────
    def sync_services(self) -> None:
        """Re-attach the current dependencies to any built service."""
        if self._people_svc is not None:
            self._people_svc.attach(PeopleDeps(
                memory=self.memory, engine=self.engine,
                labels=self.labels, undo=self._undo_svc, bus=self.bus))
        if self._undo_svc is not None:
            self._undo_svc.attach(UndoDeps(
                archive=self.archive, people=self._people_svc,
                labels=self.labels, dbs=self.dbs,
                memory=self.memory, engine=self.engine, bus=self.bus))
        if self._cdp_svc is not None:
            self._cdp_svc.attach(cdp=self.cdp, bus=self.bus)
        self._crosswire()

    def attach_archive(self, archive) -> None:
        self.archive = archive
        self.sync_services()
