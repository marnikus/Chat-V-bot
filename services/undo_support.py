"""Undo collaborators extracted from `services/undo_service.py` (AREA C).

`UndoProjection` holds the PURE timeline reads — migrating the stored
`undo_history`, migrating the legacy `stack_history`/`grid_layout_history`/
`grid_layout` config, clamping the pointer, and projecting per-kind views.
No I/O, no config writes: every caller that needs to persist a projection
does it through `UndoService` (the host), exactly as before.

`UndoWorldStore` holds the WORLD-bound half of the ONE global timeline —
the active world's `undo_history` table. The app-bound half stays in
`config/undo.json` and is written by the host's `ConfigManager`. Pending
save tasks live on the HOST (`host._undo_pendings`) so the existing
tests that read `UndoService._undo_pendings` keep working unchanged.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any, Callable, Optional

from services.layout_service import LayoutService
from services.run import normalize_blocks
from stores.undo_store import MAX_STACK_HISTORY

log = logging.getLogger("chatbot")


class UndoProjection:
    """Pure reads and projections over the global undo timeline."""

    def __init__(self, entry_builder: Callable[[str, Any], dict]):
        self._entry = entry_builder          # (kind, value) -> entry dict

    # ── migration ────────────────────────────────────────────────
    def from_raw_history(self, config, raw: list) -> tuple[list, int]:
        """Validate the stored `undo_history` per kind, preserving `seq`.

        Invalid shapes are skipped; `seq` is kept when it is a positive
        int (it is the identity used to merge the config half with the
        active world's `undo_history` table).
        """
        history = [m for m in (self._migrate_entry(e) for e in raw) if m]
        index = config.get_state("undo_history_index", len(history) - 1)
        index = index if isinstance(index, int) else len(history) - 1
        index = self.clamp_index(index, len(history))
        return history, index

    def _migrate_entry(self, entry) -> Optional[dict]:
        """One stored entry validated per kind; None when it is invalid."""
        if not isinstance(entry, dict):
            return None
        kind = entry.get("kind")
        value = entry.get("value")
        if kind == "stack" and isinstance(value, list):
            return self._migrated(entry, "stack", value)
        if kind == "grid" and isinstance(value, str):
            return self._migrate_grid(entry, value)
        if kind == "people" and isinstance(value, dict):
            return self._migrate_people(entry, value)
        if kind in ("labels", "archive", "dbconn") and \
                isinstance(value, dict):
            return self._migrated(entry, kind, value)
        return None

    def _migrate_grid(self, entry: dict, value: str) -> Optional[dict]:
        """A stored grid snapshot, canonicalised; None when it is invalid."""
        canonical, err = LayoutService.canonical_grid_payload(value)
        if not err:
            return self._migrated(entry, "grid", canonical)
        return None

    def _migrate_people(self, entry: dict, value: dict) -> Optional[dict]:
        """A stored people command; None when before/after are not lists."""
        if isinstance(value.get("before"), list) and \
                isinstance(value.get("after"), list):
            return self._migrated(entry, "people", value)
        return None

    def from_legacy_config(self, config) -> tuple[list, int, Optional[str]]:
        """Migrate the pre-global-history config keys.

        Returns `(history, index, canonical_grid)` — the canonical grid is
        the value that must be written BACK into `grid_layout` by the
        caller (the projection itself never writes).
        """
        history: list[dict] = []
        self._migrate_legacy_stacks(config, history)
        self._migrate_legacy_grids(config, history)
        canonical_grid = self._append_current_grid(config, history)
        history = self._cap(history)
        index = self._legacy_index(config, history)
        return history, index, canonical_grid

    def _migrate_legacy_stacks(self, config, history: list) -> None:
        legacy_stacks = config.get_state("stack_history", [])
        if isinstance(legacy_stacks, list):
            history.extend(self._entry("stack", s)
                           for s in legacy_stacks if isinstance(s, list))

    def _migrate_legacy_grids(self, config, history: list) -> None:
        legacy_grids = config.get_state("grid_layout_history", [])
        if isinstance(legacy_grids, list):
            for grid_value in legacy_grids:
                if not isinstance(grid_value, str):
                    continue
                canonical, err = LayoutService.canonical_grid_payload(
                    grid_value)
                if not err:
                    history.append(self._entry("grid", canonical))

    def _append_current_grid(self, config, history: list) -> Optional[str]:
        """The CURRENT grid canonicalised; appended when it differs from
        the last history entry (the caller writes it back)."""
        grid = config.get_state("grid_layout", None)
        if not (isinstance(grid, str) and grid):
            return None
        canonical, err = LayoutService.canonical_grid_payload(grid)
        if err:
            return None
        current = (history[-1]["value"]
                   if history and history[-1]["kind"] == "grid" else None)
        if canonical != current:
            history.append(self._entry("grid", canonical))
        return canonical

    @staticmethod
    def _cap(history: list) -> list:
        return history[-MAX_STACK_HISTORY:] \
            if len(history) > MAX_STACK_HISTORY else history

    def _legacy_index(self, config, history: list) -> int:
        """has_grid → last; else the stored pointer clamped; else last."""
        has_grid = bool(history and history[-1].get("kind") == "grid")
        legacy_index = config.get_state("stack_history_index", -1)
        if has_grid:
            return len(history) - 1
        if isinstance(legacy_index, int):
            return self.clamp_index(legacy_index, len(history))
        return len(history) - 1

    def _migrated(self, source: dict, kind: str, value) -> dict:
        """Rebuild a stored timeline entry, PRESERVING its seq."""
        entry = self._entry(kind, value)
        seq = source.get("seq")
        if isinstance(seq, int) and seq > 0:
            entry["seq"] = seq
        return entry

    # ── helpers ──────────────────────────────────────────────────
    @staticmethod
    def clamp_index(index, length: int) -> int:
        return max(-1, min(index, length - 1)) if isinstance(index, int) \
            else length - 1

    @classmethod
    def clean(cls, history: list) -> list[dict]:
        """Stack snapshots through `normalize_blocks`; bad rows dropped."""
        cleaned = []
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if entry.get("kind") == "stack":
                entry["value"] = normalize_blocks(entry["value"])
            cleaned.append(entry)
        return cleaned

    @staticmethod
    def stack_projection(history: list, index: int) -> tuple[list, int]:
        stacks = [e["value"] for e in history if e.get("kind") == "stack"]
        local = sum(1 for e in history[:index + 1]
                    if e.get("kind") == "stack") - 1
        return stacks, max(-1, min(local, len(stacks) - 1))

    @staticmethod
    def kind_projection(history: list, index: int, kind: str) \
            -> tuple[list, int]:
        values = [e["value"] for e in history if e.get("kind") == kind]
        local = sum(1 for e in history[:index + 1]
                    if e.get("kind") == kind) - 1
        return values, max(-1, min(local, len(values) - 1))


class UndoWorldStore:
    """The world-bound half of the ONE global undo timeline.

    Owns the `undo_history` TABLE of the active world (people / labels /
    archive / dbconn entries). Pending save tasks live on the host
    (`host._undo_pendings`), keeping `UndoService._undo_pendings` intact
    for the existing tests that read it directly.
    """

    WORLD_UNDO_KINDS = ("people", "labels", "archive", "dbconn")

    def __init__(self, host):
        self._host = host

    @property
    def _archive(self):
        return self._host._archive

    def is_open(self) -> bool:
        service = self._archive
        return service is not None and getattr(service.db, "is_open", False)

    def split(self, history: list) -> tuple[list, list]:
        """(app_entries, world_entries) — the ownership split of ONE line."""
        app = [e for e in history
               if e.get("kind") not in self.WORLD_UNDO_KINDS]
        world = [e for e in history if e.get("kind") in self.WORLD_UNDO_KINDS]
        return app, world

    def schedule_save(self, entries: list) -> None:
        """Persist the world half, tracking the task for `settle()`."""
        service = self._archive
        if service is None or not getattr(service.db, "is_open", False):
            return

        async def runner():
            try:
                await service.save_world_undo(entries)
            except Exception as exc:                   # noqa: BLE001
                log.warning("world undo save failed: %s", exc)

        try:
            task = asyncio.ensure_future(runner())
        except RuntimeError:
            return
        pendings = self._host._undo_pendings
        pendings.append(task)
        task.add_done_callback(pendings.remove)

    async def settle(self) -> None:
        """Wait for every pending world save to finish."""
        pendings = self._host._undo_pendings
        if pendings:
            try:
                await asyncio.gather(*pendings, return_exceptions=True)
            except Exception:                          # noqa: BLE001
                pass

    async def load(self) -> list[dict]:
        """The active world's `undo_history` rows (guarded, best effort)."""
        service = self._archive
        if service is None or not getattr(service.db, "is_open", False):
            return []
        try:
            return await service.load_world_undo()
        except Exception as exc:                       # noqa: BLE001
            log.warning("world undo load failed: %s", exc)
            return []
