"""UndoService — the ONE global undo timeline.

Extracted from the bridge monolith (2026-09-09). Stack edits, grid edits,
people-list edits, label edits, archive deletions and DB-connection
actions all record reversible entries on a single chronological timeline
(capped at MAX_STACK_HISTORY). The timeline is split by ownership:
app-level entries (stack/grid) persist in config/undo.json; world-bound
entries (people/labels/archive/dbconn) persist in the active world's
``undo_history`` table and die with the world.

Qt-free: services and bridges react to UndoHistoryChanged /
UserDbChanged / DbChanged / LabelsChanged / StackLoaded /
GridLayoutChanged / LogMessage events on the EventBus.

Since the god-class round's step 7 (2026-09-13) this module is a package, one
responsibility per leaf:

    entries        entry identity (_values_equal / _same_entry / _position_of)
    timeline       entry shape, cleaning, seq, history read/write, migration
    worldsync      the config half + the world table, merged by seq
    recording      push (dedupe at the pointer, honour the cap)
    projections    the stack-era compat names (push_stack & friends)
    commands       apply a COMMAND kind in either direction, rewind on refusal
    dbconn         the DB Connection ops and the world they announce
    world_change   emit_db_change / restart_world (the world-change wire half)
    snapshots      _apply_entry — walking onto a stack/grid snapshot
    walking        undo / redo
    service        the UndoService facade (vocabulary, construction, wiring)

This ``__init__`` re-exports the frozen seam — `UndoService` for
`bridge/context.py` and `bridge/router.py`; `emit_db_change` / `restart_world`
for `bridge/db_bridge.py`; `_values_equal` for the router's wire class; the
other module-level helpers that used to sit beside the class; `LayoutService`
(API parity, as before); and `MAX_STACK_HISTORY`, which
`tests/test_world_write_gate.py` rebinds to shrink the cap (read at call time
by `recording._history_cap`, so that patch still lands on the code that runs).
Promoting the module to a package changed no import line anywhere.

See `docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from backend.config_manager import MAX_STACK_HISTORY  # noqa: F401  patch seam
from services.layout_service import LayoutService  # noqa: F401  API parity

from .commands import (_apply_labels_command, _apply_people_command,
                       _log_command)
from .entries import _position_of, _same_entry, _values_equal
from .service import UndoService
from .world_change import emit_db_change, log, restart_world

__all__ = [
    "UndoService",
    "emit_db_change",
    "restart_world",
    "_values_equal",
    "_same_entry",
    "_position_of",
    "_apply_people_command",
    "_apply_labels_command",
    "_log_command",
    "MAX_STACK_HISTORY",
    "LayoutService",
    "log",
]
