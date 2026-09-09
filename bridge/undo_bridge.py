"""UndoBridge — global undo/redo timeline."""

from __future__ import annotations

import json
import logging
import copy
from PySide6.QtCore import QObject, Signal, Slot
from backend.config_manager import MAX_STACK_HISTORY

log = logging.getLogger("chatbot")


class UndoBridge(QObject):
    history_changed = Signal()
    grid_layout_changed = Signal(str)
    log_message = Signal(str, str)

    def __init__(self, ctx: dict, parent=None):
        super().__init__(parent)
        self._config = ctx.get("config")
        self._engine = ctx.get("engine")
        self._memory = ctx.get("memory")

    def _get_hist(self):
        raw=self._config.get_state("undo_history",None)
        idx=self._config.get_state("undo_history_index",-1)
        hist=copy.deepcopy(raw) if isinstance(raw,list) else []
        return hist, int(idx) if isinstance(idx,int) else len(hist)-1

    def _set_hist(self, hist, idx):
        if len(hist)>MAX_STACK_HISTORY:
            overflow=len(hist)-MAX_STACK_HISTORY; hist=hist[overflow:]; idx-=overflow
        self._config.set_state(undo_history=copy.deepcopy(hist), undo_history_index=int(idx))
        self.history_changed.emit()

    @Slot(result=str)
    def get_undo_history(self):
        h,i=self._get_hist(); return json.dumps({"history":h,"index":i},ensure_ascii=False)

    @Slot(str, str, result=bool)
    def push_global_history(self, kind, value_json):
        try: val=json.loads(value_json or "[]")
        except json.JSONDecodeError: return False
        hist,idx=self._get_hist()
        entry={"kind":kind,"value":val}
        if idx < len(hist)-1: hist=hist[:idx+1]
        hist.append(entry); idx=len(hist)-1
        self._set_hist(hist,idx)
        return True

    @Slot(result=str)
    def undo(self):
        hist,idx=self._get_hist()
        if not hist or idx<0: self.log_message.emit("⚠ Nothing to undo","warn"); return "null"
        if idx<=0: self.log_message.emit("⚠ Nothing to undo","warn"); return "null"
        idx-=1; self._set_hist(hist,idx); self.log_message.emit("↩ Undo","info")
        e=hist[idx]; return json.dumps({"kind":e["kind"],"value":e["value"],"index":idx},ensure_ascii=False)

    @Slot(result=str)
    def redo(self):
        hist,idx=self._get_hist()
        if not hist or idx>=len(hist)-1: self.log_message.emit("⚠ Nothing to redo","warn"); return "null"
        idx+=1; self._set_hist(hist,idx); self.log_message.emit("↪ Redo","info")
        e=hist[idx]; return json.dumps({"kind":e["kind"],"value":e["value"],"index":idx},ensure_ascii=False)

    @Slot(result=str)
    def get_stack_history(self):
        hist,idx=self._get_hist(); stacks=[e["value"] for e in hist if e.get("kind")=="stack"]
        sidx=sum(1 for e in hist[:idx+1] if e.get("kind")=="stack")-1
        return json.dumps({"history":stacks,"index":sidx},ensure_ascii=False)
