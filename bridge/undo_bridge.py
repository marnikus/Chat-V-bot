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
from bridge.wire_undo import global_payload, kind_value, list_arg, trim_history

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

    _global_payload = staticmethod(global_payload)

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
        return kind_value(self.undo(), "stack")

    @Slot(result=str)
    def redo_stack(self):
        return kind_value(self.redo(), "stack")

    @Slot(result=str)
    def undo_grid_layout(self):
        return kind_value(self.undo(), "grid")

    @Slot(result=str)
    def redo_grid_layout(self):
        return kind_value(self.redo(), "grid")

    # ── legacy stack-history slots (frontend bulk save / restore) ─
    @Slot(result=str)
    def get_stack_history(self):
        hist, idx = self.undo_service.stack_projection()
        return json.dumps({"history": hist, "index": idx},
                          ensure_ascii=False)

    @Slot(str)
    def push_stack_history(self, stack_json):
        blocks = list_arg(stack_json)
        if blocks is not None:
            self.undo_service.push_stack(blocks)

    @Slot(str, int)
    def save_stack_history(self, history_json, index):
        hist = list_arg(history_json)
        if hist is None:
            return
        hist = self.undo_service._clean_history(hist)
        from backend.config_manager import MAX_STACK_HISTORY
        hist, index = trim_history(hist, index, MAX_STACK_HISTORY)
        self.undo_service.set_stack_projection(hist, index)
        log.info("History saved from frontend: %d entries, index %d",
                 len(hist), index)
