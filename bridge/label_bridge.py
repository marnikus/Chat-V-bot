"""LabelBridge — person labels domain."""

from __future__ import annotations

import json
import logging
from PySide6.QtCore import QObject, Signal, Slot

from backend.label_store import LabelStore

log = logging.getLogger("chatbot")


class LabelBridge(QObject):
    labels_changed = Signal(str)
    log_message = Signal(str, str)

    def __init__(self, ctx: dict, parent=None):
        super().__init__(parent)
        self._config = ctx.get("config")
        self._memory = ctx.get("memory")
        self._engine = ctx.get("engine")
        self._labels = LabelStore(self._config)
        if self._engine:
            try:
                self._engine.label_filter = self._labels.allows
                self._engine.label_reason = self._labels.reject_reason
            except Exception:
                pass

    @property
    def label_store(self): return self._labels

    def _emit(self):
        self.labels_changed.emit(json.dumps(self._labels.state(), ensure_ascii=False))

    @Slot(result=str)
    def get_labels(self): return json.dumps(self._labels.state(), ensure_ascii=False)

    @Slot(str, str, result=str)
    def label_create(self, name, color):
        made=self._labels.create(name,color)
        if made: self._emit(); self.log_message.emit(f"🏷 Label “{made.get('name')}” created","success"); return json.dumps(made,ensure_ascii=False)
        self.log_message.emit(f"⚠ Label “{name}” already exists","warn"); return "null"

    @Slot(str, str, str, result=bool)
    def label_update(self, label_id, name, color):
        ok=bool(self._labels.update(label_id, name if name else None, color if color else None))
        if ok: self._emit(); self.log_message.emit("🏷 Label updated","info")
        return ok

    @Slot(str, result=bool)
    def label_delete(self, label_id):
        ok=self._labels.delete(label_id)
        if ok: self._emit()
        return bool(ok)

    @Slot(str, str, result=bool)
    def label_assign(self, nick, label_id):
        ok=self._labels.assign(nick,label_id)
        if ok: self._emit()
        return bool(ok)

    @Slot(str, str, result=bool)
    def label_unassign(self, nick, label_id):
        ok=self._labels.unassign(nick,label_id)
        if ok: self._emit()
        return bool(ok)

    @Slot(str, str, result=bool)
    def label_set_for(self, nick, ids_json):
        try: ids=json.loads(ids_json or "[]")
        except json.JSONDecodeError: return False
        ok=self._labels.set_for(nick, ids)
        if ok: self._emit()
        return bool(ok)

    @Slot(str, result=bool)
    def label_set_filter(self, rule_json):
        try: rule=json.loads(rule_json or "{}")
        except json.JSONDecodeError: return False
        ok=self._labels.set_filter(rule.get("include") or [], rule.get("exclude") or [])
        if ok is not None: self._emit(); return True
        return False

    @Slot(result=bool)
    def label_clear_filter(self):
        ok=self._labels.clear_filter()
        if ok is not None: self._emit(); return True
        return False
