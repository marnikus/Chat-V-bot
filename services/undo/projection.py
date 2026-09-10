"""Normalization and legacy projections of the single undo timeline."""

from __future__ import annotations
import copy
from services.layout_service import LayoutService
from services.run import normalize_blocks


class UndoProjection:
    @staticmethod
    def _clean_blocks(blocks):
        """Strip retired block keys from stack snapshots (safety net)."""
        return normalize_blocks(blocks)

    @classmethod
    def _clean_history(cls, hist):
        if not isinstance(hist, list):
            return []
        return [cls._clean_blocks(entry) for entry in hist if isinstance(entry, list)]

    @staticmethod
    def _history_entry(kind, value):
        return {"kind": kind, "value": copy.deepcopy(value)}

    def _migrated_entry(self, source: dict, kind: str, value) -> dict:
        """Rebuild a stored timeline entry, PRESERVING its seq.

        seq is the identity used to merge the app-level config half with the
        active world's ``undo_history`` table on startup. Dropping it (as a
        plain rebuild did) pushed every app entry ahead of the world entries
        in the merged timeline and could issue duplicate seqs — the global
        undo order was wrong after a restart.
        """
        entry = self._history_entry(kind, value)
        seq = source.get("seq")
        if isinstance(seq, int) and seq > 0:
            entry["seq"] = seq
        return entry

    @staticmethod
    def _clamp_index(index, history) -> int:
        if not isinstance(index, int):
            index = len(history) - 1
        return max(-1, min(index, len(history) - 1))

    def _normalize_stored_entry(self, entry):
        if not isinstance(entry, dict):
            return None
        kind, value = entry.get("kind"), entry.get("value")
        if kind == "grid":
            if not isinstance(value, str):
                return None
            value, error = LayoutService.canonical_grid_payload(value)
            if error:
                return None
        elif kind == "stack":
            if not isinstance(value, list):
                return None
        elif not self._valid_command(kind, value):
            return None
        return self._migrated_entry(entry, kind, value)

    @staticmethod
    def _valid_command(kind, value) -> bool:
        if not isinstance(value, dict):
            return False
        if kind == "people":
            return isinstance(value.get("before"), list) and isinstance(
                value.get("after"), list
            )
        return kind in ("labels", "archive", "dbconn")

    def _legacy_snapshots(self) -> list:
        history = []
        for key, kind in (("stack_history", "stack"), ("grid_layout_history", "grid")):
            raw = self._config.get_state(key, [])
            if not isinstance(raw, list):
                continue
            for value in raw:
                entry = self._normalize_stored_entry({"kind": kind, "value": value})
                if entry is not None:
                    history.append(entry)
        return history

    def _append_current_grid(self, history) -> None:
        grid = self._config.get_state("grid_layout", None)
        if not isinstance(grid, str) or not grid:
            return
        canonical, error = LayoutService.canonical_grid_payload(grid)
        if error:
            return
        current = (
            history[-1]["value"] if history and history[-1]["kind"] == "grid" else None
        )
        if canonical != current:
            history.append(self._history_entry("grid", canonical))
        self._config.set_state(grid_layout=canonical)

    def migrate_global_history(self) -> tuple[list, int]:
        """Validate modern entries, or migrate legacy snapshots exactly once."""
        raw = self._config.get_state("undo_history", None)
        if isinstance(raw, list) and raw:
            history = [
                clean
                for entry in raw
                if (clean := self._normalize_stored_entry(entry)) is not None
            ]
            index = self._config.get_state("undo_history_index", len(history) - 1)
            return history, self._clamp_index(index, history)
        history = self._legacy_snapshots()
        self._append_current_grid(history)
        history = history[-self.HISTORY_LIMIT :]
        index = self._config.get_state("stack_history_index", -1)
        if history and history[-1]["kind"] == "grid":
            index = len(history) - 1
        index = self._clamp_index(index, history)
        self._config.set_state(undo_history=history, undo_history_index=index)
        return history, index

    def stack_projection(self) -> tuple[list, int]:
        """Compatibility projection of stack entries."""
        return self.kind_projection("stack")

    def set_stack_projection(
        self, history: list, index: int, save: bool = True
    ) -> None:
        entries = [
            self._history_entry("stack", self._clean_blocks(value))
            for value in history
            if isinstance(value, list)
        ]
        self.set_history(entries, max(-1, min(index, len(entries) - 1)))

    def kind_projection(self, kind: str) -> tuple[list, int]:
        history, global_index = self.history()
        values = [e["value"] for e in history if e.get("kind") == kind]
        local_index = (
            sum(1 for e in history[: global_index + 1] if e.get("kind") == kind) - 1
        )
        return values, max(-1, min(local_index, len(values) - 1))
