"""LabelBridge — person labels: definitions, assignment, filter rule.

Every label mutation is ONE reversible entry on the global timeline
(the UndoService owns the timeline). The LabelStore (stores/label_store.py)
is world-bound: its data lives in the active database.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.events import LabelsChanged, LogMessage

log = logging.getLogger("chatbot")


class LabelBridge(QObject):
    labels_changed = Signal(str)             # JSON: the whole labels state

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        ctx.bus.subscribe(LabelsChanged,
                          lambda e: self.labels_changed.emit(e.payload))

    @property
    def label_store(self):
        return self.ctx.label_store()

    def _emit_labels(self) -> None:
        state = self.label_store.state()
        self.labels_changed.emit(json.dumps(state, ensure_ascii=False))

    def _labels_edit(self, mutate, message: str = "") -> bool:
        """Run a labels mutation as ONE reversible entry of the timeline."""
        store = self.label_store
        before = store.snapshot()
        changed = bool(mutate(store))
        if not changed:
            return False
        after = store.snapshot()
        if self._values_equal(before, after):
            return False
        self.ctx.undo.push("labels", {"before": before, "after": after})
        self._emit_labels()
        if message:
            self.ctx.bus.emit(LogMessage(message=message, level="info"))
        # Labels can hide people from the queue, so the # column changes.
        from core.events import PeopleChanged
        self.ctx.bus.emit(PeopleChanged(reason="labels"))
        return True

    @staticmethod
    def _values_equal(a, b) -> bool:
        try:
            return json.dumps(a, sort_keys=True, ensure_ascii=False) == \
                   json.dumps(b, sort_keys=True, ensure_ascii=False)
        except Exception:                               # noqa: BLE001
            return a == b

    # ── engine guard ─────────────────────────────────────────────
    def install_label_guard(self) -> None:
        """Let a run skip people carrying an excluded label."""
        engine = self.ctx.engine
        if engine is None:
            return
        try:
            engine.label_filter = self.label_store.allows
            engine.label_reason = self.label_store.reject_reason
        except Exception as exc:                        # noqa: BLE001
            log.debug("label guard not installed: %s", exc)

    # ── slots ────────────────────────────────────────────────────
    @Slot(result=str)
    def get_labels(self):
        return json.dumps(self.label_store.state(), ensure_ascii=False)

    @Slot(str, str, result=str)
    def label_create(self, name, color):
        created = {}

        def mutate(store):
            made = store.create(name, color)
            if made:
                created.update(made)
            return bool(made)

        if not self._labels_edit(mutate, ""):
            self.ctx.bus.emit(LogMessage(
                message=f"⚠ Label “{name}” already exists (or has no name)",
                level="warn"))
            return "null"
        self.ctx.bus.emit(LogMessage(
            message=f"🏷 Label “{created.get('name')}” created",
            level="success"))
        return json.dumps(created, ensure_ascii=False)

    @Slot(str, str, str, result=bool)
    def label_update(self, label_id, name, color):
        return self._labels_edit(
            lambda store: bool(store.update(label_id,
                                            name if name else None,
                                            color if color else None)),
            "🏷 Label updated")

    @Slot(str, result=bool)
    def label_delete(self, label_id):
        label = self.label_store.by_id(label_id)
        title = label["name"] if label else label_id
        return self._labels_edit(lambda store: store.delete(label_id),
                                 f"🗑 Label “{title}” removed everywhere")

    @Slot(str, str, result=bool)
    def label_assign(self, nick, label_id):
        return self._labels_edit(lambda store: store.assign(nick, label_id),
                                 "")

    @Slot(str, str, result=bool)
    def label_unassign(self, nick, label_id):
        return self._labels_edit(
            lambda store: store.unassign(nick, label_id), "")

    @Slot(str, str, result=bool)
    def label_set_for(self, nick, ids_json):
        try:
            ids = json.loads(ids_json or "[]")
        except json.JSONDecodeError:
            return False
        if not isinstance(ids, list):
            return False
        return self._labels_edit(lambda store: store.set_for(nick, ids),
                                 f"🏷 Labels of “{nick}” updated")

    @Slot(str, result=bool)
    def label_set_filter(self, rule_json):
        try:
            rule = json.loads(rule_json or "{}")
        except json.JSONDecodeError:
            return False
        if not isinstance(rule, dict):
            return False
        include = rule.get("include") or []
        exclude = rule.get("exclude") or []
        return self._labels_edit(
            lambda store: store.set_filter(include, exclude) is not None,
            "🏷 Label filter updated")

    @Slot(result=bool)
    def label_clear_filter(self):
        return self._labels_edit(
            lambda store: bool(store.filter_active) and
            store.clear_filter() is not None,
            "🏷 Label filter cleared")
