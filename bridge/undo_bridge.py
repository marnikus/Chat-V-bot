"""UndoBridge — the global undo timeline's JS surface.

The UndoService (services/undo_service.py) owns the timeline; this bridge
translates Results into the wire payloads and keeps the compatibility
slots (per-surface undo/redo aliases) alive.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.events import LogMessage, UndoHistoryChanged
from core.result import Err, Ok
from services.layout_service import LayoutService

log = logging.getLogger("chatbot")


class UndoBridge(QObject):
    history_changed = Signal()              # global timeline grew / moved

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        ctx.bus.subscribe(UndoHistoryChanged,
                          lambda _e: self.history_changed.emit())

    @property
    def undo_service(self):
        return self.ctx.undo

    # ── the global timeline ──────────────────────────────────────
    @Slot(result=str)
    def get_undo_history(self):
        history, index = self.undo_service.history()
        return json.dumps({"history": history, "index": index},
                          ensure_ascii=False)

    @Slot(str, str, result=bool)
    def push_global_history(self, kind, value_json):
        """Record a frontend edit in the one global timeline."""
        accepted, value = self._global_payload(kind, value_json)
        if not accepted:
            return False
        result = self.undo_service.push(kind, value)
        if result.is_err:
            return False
        self._remember_global_edit(kind, value)
        return True

    @staticmethod
    def _global_payload(kind: str, value_json: str) -> tuple:
        """(accepted, value) for one frontend edit of the global timeline.

        Only `stack` and `grid` are global-timeline kinds. Anything else is
        refused rather than recorded: an unvalidated payload would make every
        later undo step lie about what it restores.
        """
        if kind == "stack":
            try:
                value = json.loads(value_json or "[]")
            except json.JSONDecodeError:
                return False, None
            return isinstance(value, list), value
        if kind == "grid":
            value, err = LayoutService.canonical_grid_payload(value_json or "")
            return not err, value
        return False, None

    def _remember_global_edit(self, kind: str, value) -> None:
        """Persist the edit the timeline has just accepted."""
        if kind == "grid":
            self.ctx.config.set_state(grid_layout=value)
            return
        if kind != "stack":
            return
        self.ctx.config.set_state(last_stack=value, last_stack_preset="")
        # The stack determines the processing order (# column):
        # re-rank the people list when a block is added/removed.
        from core.events import PeopleChanged
        self.ctx.bus.emit(PeopleChanged(reason="stack"))

    @Slot(result=str)
    def undo(self):
        result = self.undo_service.undo()
        if result.is_err:
            self.ctx.bus.emit(LogMessage(message="⚠ Nothing to undo",
                                         level="warn"))
            return "null"
        return json.dumps(result.value, ensure_ascii=False)

    @Slot(result=str)
    def redo(self):
        result = self.undo_service.redo()
        if result.is_err:
            self.ctx.bus.emit(LogMessage(message="⚠ Nothing to redo",
                                         level="warn"))
            return "null"
        return json.dumps(result.value, ensure_ascii=False)

    # ── per-surface compatibility aliases (the one global operation
    #    projected through the old per-surface names) ─────────────
    @Slot(result=str)
    def undo_stack(self):
        raw = self.undo()
        try:
            result = json.loads(raw)
            return json.dumps(result["value"], ensure_ascii=False) \
                if isinstance(result, dict) and \
                result.get("kind") == "stack" else "null"
        except (TypeError, KeyError, json.JSONDecodeError):
            return "null"

    @Slot(result=str)
    def redo_stack(self):
        raw = self.redo()
        try:
            result = json.loads(raw)
            return json.dumps(result["value"], ensure_ascii=False) \
                if isinstance(result, dict) and \
                result.get("kind") == "stack" else "null"
        except (TypeError, KeyError, json.JSONDecodeError):
            return "null"

    @Slot(result=str)
    def undo_grid_layout(self):
        raw = self.undo()
        try:
            result = json.loads(raw)
            return (LayoutService.legacy_grid_payload(result.get("value",
                                                                 "null"))
                    if isinstance(result, dict)
                    and result.get("kind") == "grid" else "null")
        except (TypeError, json.JSONDecodeError):
            return "null"

    @Slot(result=str)
    def redo_grid_layout(self):
        raw = self.redo()
        try:
            result = json.loads(raw)
            return (LayoutService.legacy_grid_payload(result.get("value",
                                                                 "null"))
                    if isinstance(result, dict)
                    and result.get("kind") == "grid" else "null")
        except (TypeError, json.JSONDecodeError):
            return "null"

    # ── legacy stack-history slots (frontend bulk save / restore) ─
    @Slot(result=str)
    def get_stack_history(self):
        hist, idx = self.undo_service.stack_projection()
        return json.dumps({"history": hist, "index": idx},
                          ensure_ascii=False)

    @Slot(str)
    def push_stack_history(self, stack_json):
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return
        if isinstance(blocks, list):
            self.undo_service.push_stack(blocks)

    @Slot(str, int)
    def save_stack_history(self, history_json, index):
        try:
            hist = json.loads(history_json or "[]")
        except json.JSONDecodeError:
            return
        if not isinstance(hist, list):
            return
        if not isinstance(index, int):
            index = -1
        hist = self.undo_service._clean_history(hist)
        from backend.config_manager import MAX_STACK_HISTORY
        if len(hist) > MAX_STACK_HISTORY:
            overflow = len(hist) - MAX_STACK_HISTORY
            hist = hist[overflow:]
            index = max(0, index - overflow)
        self.undo_service.set_stack_projection(hist, index)
        log.info("History saved from frontend: %d entries, index %d",
                 len(hist), index)
