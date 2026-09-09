"""LayoutBridge — sash grid layout + window states."""

from __future__ import annotations

import json
import logging
import copy
from PySide6.QtCore import QObject, Signal, Slot

log = logging.getLogger("chatbot")


class LayoutBridge(QObject):
    grid_layout_changed = Signal(str)
    grid_layout_persisted = Signal(bool)
    log_message = Signal(str, str)
    history_changed = Signal()

    WINDOW_IDS = {"stats","filters","stack","config","composer","people","log","history","userdb","collector","labels","dbconn"}
    GRID_VERSION = 3

    def __init__(self, ctx: dict, parent=None):
        super().__init__(parent)
        self._config = ctx.get("config")
        self._engine = ctx.get("engine")

    def _canonical(self, raw: str):
        try: data=json.loads(raw)
        except Exception as exc: return None, f"bad JSON ({exc})"
        if not isinstance(data, dict): return None, "payload must be object"
        v=data.get("v")
        if not isinstance(v,int) or not 1<=v<=self.GRID_VERSION: return None, f"unsupported version {v!r}"
        return json.dumps({"v":self.GRID_VERSION,"tree":data.get("tree")},ensure_ascii=False, separators=(",",":")), None

    @Slot(result=str)
    def get_grid_layout(self):
        raw=self._config.get_state("grid_layout",None)
        if not isinstance(raw,str) or not raw: return ""
        payload,err=self._canonical(raw)
        return payload if not err else ""

    @Slot(str, result=bool)
    def save_grid_layout(self, layout_json):
        payload,err=self._canonical(layout_json or "")
        if err: log.warning("Grid layout rejected: %s",err); self.log_message.emit(f"⚠ Grid layout not saved: {err}","warn"); self.grid_layout_persisted.emit(False); return False
        self._config.set_state(grid_layout=payload)
        # push to undo
        try:
            hist=self._config.get_state("undo_history",[]) or []; idx=self._config.get_state("undo_history_index",-1)
            hist=copy.deepcopy(hist) if isinstance(hist,list) else []
            entry={"kind":"grid","value":payload}
            if idx < len(hist)-1: hist=hist[:idx+1]
            hist.append(entry); idx=len(hist)-1
            self._config.set_state(undo_history=hist, undo_history_index=idx)
            self.history_changed.emit()
        except Exception:
            pass
        self.grid_layout_persisted.emit(True); return True

    @Slot(result=str)
    def reset_grid_layout(self):
        payload=json.dumps({"v":self.GRID_VERSION,"tree":{"t":"split","dir":"col","children":[{"t":"leaf","id":"stats"}],"sizes":[100]}}, ensure_ascii=False, separators=(",",":"))
        self._config.set_state(grid_layout=payload, window_states={"closed":[],"minimized":[]})
        self.log_message.emit("↺ Grid layout reset","info")
        return payload

    @Slot(result=str)
    def get_window_states(self):
        raw=self._config.get_state("window_states",None)
        if isinstance(raw,dict):
            closed=[i for i in raw.get("closed",[]) if isinstance(i,str) and i in self.WINDOW_IDS]
            minimized=[i for i in raw.get("minimized",[]) if isinstance(i,str) and i in self.WINDOW_IDS and i not in closed]
            return json.dumps({"closed":closed,"minimized":minimized},ensure_ascii=False)
        return ""

    @Slot(str, result=bool)
    def save_window_states(self, states_json):
        try: data=json.loads(states_json or "{}")
        except json.JSONDecodeError: return False
        if not isinstance(data,dict): return False
        closed=[i for i in data.get("closed",[]) if isinstance(i,str) and i in self.WINDOW_IDS]
        minimized=[i for i in data.get("minimized",[]) if isinstance(i,str) and i in self.WINDOW_IDS and i not in closed]
        self._config.set_state(window_states={"closed":closed,"minimized":minimized})
        return True

    @Slot(bool)
    def set_block_config_pinned(self, pinned): self._config.set_state(block_config_pinned=bool(pinned))
