"""Person labels: custom coloured tags — ONE world's data, per database.

Since the unified single-DB redesign (2026-09-08, docs/
DB_CREATION_DELETION_REDESIGN_DESIGN_2026-09-08.md) labels belong to the
WORLD they were created in: the definitions live in the `labels` table and
the person→label mapping in `label_assigns` inside the active database file,
so deleting a database takes its labels with it and loading another one
shows only that world's tags (no cross-DB leakage).

The class keeps a fully SYNCHRONOUS read API because the run queue and the
engine's label guard call it from non-async code paths:

* `LabelStore(config)` — legacy/offline mode: the config.json `labels`
  section is the store (hand-assembled bridges, unit tests, or a moment
  before the archive service is up).
* `LabelStore(config, db, scheduler)` — world mode: `db` is the open
  `HistoryDB`; every mutation updates the in-memory state immediately and
  schedules an async write-through to the database (`scheduler(coro)`).
  `await store.load_from_db(db)` / `await store.switch_db(db)` move the
  world; `await store.flush_to_db()` empties the dirty queue.

Shape of the in-memory state (same as the old config section, so undo
snapshots keep working unchanged)::

    {
      "defs":   [{"id": "lbl_1", "name": "Rude", "color": "#ff3b30",
                  "created_at": "2026-09-07T18:22:31"}],
      "assign": {"Angelochenek": ["lbl_1", "lbl_2"]},
      "filter": {"include": ["lbl_3"], "exclude": ["lbl_1"]},
      "next_id": 4
    }

The include/exclude filter is a per-world setting: it persists in the
database's `app_settings` table under the key `label_filter`.

Everything is normalised on read: unknown ids, broken colours and duplicate
names can never reach the UI or crash a panel (AGENT_RULES RULE 13).
"""

from __future__ import annotations

# The rules moved to `stores/label_rules.py` with the B2 split (design §2.5);
# these names are re-exported because `backend/label_store.py` — a frozen shim
# — and five test modules import them from this module.
from stores.label_rules import (                                 # noqa: F401
    DEFAULT_COLOR,
    FILTER_KEY,
    MAX_NAME,
    PALETTE,
    normalize_color,
    normalize_id,
    normalize_name,
    normalize_nick,
)

#: what this module promises the rest of the app. `normalize_*` moved to
#: `stores/label_rules.py` in B2 and is re-exported above; `__all__` is how
#: `tools/metrics/stores_api.py` knows a re-export is still surface (design §3).
__all__ = ["LabelStore", "PALETTE", "DEFAULT_COLOR", "FILTER_KEY", "MAX_NAME",
           "normalize_color", "normalize_id", "normalize_name", "normalize_nick"]


class LabelStore:
    """Definitions, per-person assignment and the include/exclude filter."""

    SECTION = "labels"

    def __init__(self, config, db=None, scheduler=None):
        """`db`: an open `HistoryDB` (world mode), else config.json mode.
        `scheduler(coro)`: runs the async write-through (the bridge passes a
        Qt-loop helper). Mutations are always applied to memory first."""
        from stores.label_assignments import LabelAssignments
        from stores.label_filter import LabelFilter
        from stores.label_state import LabelState
        from stores.label_world import LabelWorldSync
        # local imports on purpose: the four parts read `stores.label_rules`,
        # and this module is the name `backend/label_store.py` re-exports, so
        # a module-scope import here would close a cycle through the package
        self._config = config
        self._db = db
        self._scheduler = scheduler
        self._memory: dict | None = None     # live raw state (world mode)
        self._dirty = False
        # the B2 split (design §2.5): the parts hold no state of their own —
        # every one of them reads `self._config` / `_db` / `_memory` back off
        # this object, so `store._dirty = True` from a service still works
        self._state = LabelState(self)
        self._world = LabelWorldSync(self)
        self._assignments = LabelAssignments(self)
        self._filter = LabelFilter(self)

    # ── world binding ────────────────────────────────────────────
    @property
    def db(self):
        return self._db

    @property
    def is_bound(self) -> bool:
        return self._db is not None

    def set_scheduler(self, scheduler) -> None:
        """See `LabelWorldSync.set_scheduler` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        self._world.set_scheduler(scheduler)

    async def load_from_db(self, db) -> dict:
        """See `LabelWorldSync.load_from_db` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return await self._world.load_from_db(db)

    async def flush_to_db(self) -> None:
        """See `LabelWorldSync.flush_to_db` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        await self._world.flush_to_db()

    def _schedule_flush(self) -> None:
        """See `LabelWorldSync._schedule_flush` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        self._world._schedule_flush()

    async def _guarded_flush(self) -> None:
        """See `LabelWorldSync._guarded_flush` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        await self._world._guarded_flush()

    def _initial_state(self) -> dict:
        """See `LabelState._initial_state` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._state._initial_state()

    def _memory_state(self) -> dict:
        """See `LabelState._memory_state` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._state._memory_state()

    def _raw_config(self) -> dict:
        """See `LabelState._raw_config` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._state._raw_config()

    def _raw(self) -> dict:
        """See `LabelState._raw` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._state._raw()

    def _write(self, data: dict) -> None:
        """See `LabelState._write` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        self._state._write(data)

    def _save(self, data: dict) -> None:
        """See `LabelState._save` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        self._state._save(data)

    def _normalized(self) -> dict:
        """See `LabelState._normalized` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._state._normalized()

    # ── raw state access ─────────────────────────────────────────

    # ── normalisation ────────────────────────────────────────────

    # ── reads ────────────────────────────────────────────────────
    def defs(self) -> list[dict]:
        """See `LabelAssignments.defs` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.defs()

    def by_id(self, label_id) -> dict | None:
        """See `LabelAssignments.by_id` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.by_id(label_id)

    def by_name(self, name) -> dict | None:
        """See `LabelAssignments.by_name` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.by_name(name)

    def assignments(self) -> dict:
        """See `LabelAssignments.assignments` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.assignments()

    def ids_for(self, nick) -> list[str]:
        """See `LabelAssignments.ids_for` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.ids_for(nick)

    def labels_for(self, nick) -> list[dict]:
        """See `LabelAssignments.labels_for` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.labels_for(nick)

    def labels_map(self, nicks=None) -> dict:
        """See `LabelAssignments.labels_map` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.labels_map(nicks=nicks)

    def state(self) -> dict:
        """See `LabelAssignments.state` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.state()

    def create(self, name, color: str = "") -> dict | None:
        """See `LabelAssignments.create` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.create(name, color=color)

    def update(self, label_id, name=None, color=None) -> dict | None:
        """See `LabelAssignments.update` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.update(label_id, name=name, color=color)

    def delete(self, label_id) -> bool:
        """See `LabelAssignments.delete` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.delete(label_id)

    def assign(self, nick, label_id) -> bool:
        """See `LabelAssignments.assign` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.assign(nick, label_id)

    def unassign(self, nick, label_id) -> bool:
        """See `LabelAssignments.unassign` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.unassign(nick, label_id)

    def set_for(self, nick, ids) -> bool:
        """See `LabelAssignments.set_for` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.set_for(nick, ids)

    def forget(self, nick) -> bool:
        """See `LabelAssignments.forget` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.forget(nick)

    def snapshot(self) -> dict:
        """See `LabelAssignments.snapshot` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._assignments.snapshot()

    def restore(self, snapshot) -> None:
        """See `LabelAssignments.restore` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        self._assignments.restore(snapshot)

    # ── definitions ──────────────────────────────────────────────

    # ── assignment ───────────────────────────────────────────────

    # ── filtering ────────────────────────────────────────────────
    def filter(self) -> dict:
        """See `LabelFilter.filter` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._filter.filter()

    def set_filter(self, include=None, exclude=None) -> dict:
        """See `LabelFilter.set_filter` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._filter.set_filter(include=include, exclude=exclude)

    def clear_filter(self) -> dict:
        """See `LabelFilter.clear_filter` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._filter.clear_filter()

    def allows(self, nick) -> bool:
        """See `LabelFilter.allows` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._filter.allows(nick)

    def reject_reason(self, nick) -> str:
        """See `LabelFilter.reject_reason` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return self._filter.reject_reason(nick)

    @property
    def filter_active(self) -> bool:
        current = self.filter()
        return bool(current["include"] or current["exclude"])

    # ── undo support ─────────────────────────────────────────────

