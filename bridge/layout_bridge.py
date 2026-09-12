"""LayoutBridge — grid layout persistence, window states, session restore.

The grid tree spec (validation, versioning, migration) is the
LayoutService (services/layout_service.py); this bridge owns the @Slot
surface and re-exports the spec constants for the Router/tests.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.events import GridLayoutChanged, LogMessage
from services.layout_service import LayoutService

log = logging.getLogger("chatbot")


class LayoutBridge(QObject):
    grid_layout_changed = Signal(str)        # JSON canonical grid payload
    grid_layout_persisted = Signal(bool)     # close-time save acknowledgment

    # ── spec re-exports (class attributes; tests read them off Bridge) ─
    V1_WINDOW_IDS = LayoutService.V1_WINDOW_IDS
    V2_WINDOW_IDS = LayoutService.V2_WINDOW_IDS
    V3_WINDOW_IDS = LayoutService.V3_WINDOW_IDS
    LEGACY_WINDOW_IDS = LayoutService.LEGACY_WINDOW_IDS
    NEW_WINDOW_IDS = LayoutService.NEW_WINDOW_IDS
    WINDOW_IDS = LayoutService.WINDOW_IDS
    GRID_VERSION = LayoutService.GRID_VERSION
    MIN_GRID_SIZE = LayoutService.MIN_GRID_SIZE

    # ── spec classmethods (delegates) ────────────────────────────
    _node_type = staticmethod(LayoutService.node_type)
    _normalize_grid_tree = classmethod(
        lambda cls, node, depth=0: LayoutService.normalize_grid_tree(node,
                                                                     depth))
    _validate_grid_tree = classmethod(
        lambda cls, node, depth=0: LayoutService.validate_grid_tree(node,
                                                                    depth))
    _leaf_ids = classmethod(lambda cls, node, out=None:
                            LayoutService.leaf_ids(node, out))
    _parse_grid_payload = classmethod(
        lambda cls, raw: LayoutService.parse_grid_payload(raw))
    _migrate_grid_tree = classmethod(
        lambda cls, tree: LayoutService.migrate_grid_tree(tree))
    _canonical_grid_payload = classmethod(
        lambda cls, raw: LayoutService.canonical_grid_payload(raw))
    _default_grid_tree = classmethod(
        lambda cls: LayoutService.default_grid_tree())
    _legacy_grid_payload = classmethod(
        lambda cls, raw: LayoutService.legacy_grid_payload(raw))

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        ctx.bus.subscribe(GridLayoutChanged,
                          lambda e: self.grid_layout_changed.emit(e.payload))

    # ── grid layout ──────────────────────────────────────────────
    @Slot(result=str)
    def get_grid_layout(self):
        raw = self.ctx.config.get_state("grid_layout", None)
        if not isinstance(raw, str) or not raw:
            return ""
        payload, err = LayoutService.canonical_grid_payload(raw)
        return payload if not err else ""

    @Slot(str, result=bool)
    def save_grid_layout(self, layout_json):
        """Validate and persist a grid as one entry in global undo history."""
        payload, err = LayoutService.canonical_grid_payload(layout_json
                                                            or "")
        if err:
            log.warning("Grid layout rejected: %s", err)
            self.ctx.bus.emit(LogMessage(
                message=f"⚠ Grid layout not saved: {err}", level="warn"))
            self.grid_layout_persisted.emit(False)
            return False
        self.ctx.config.set_state(grid_layout=payload)
        self.ctx.undo.push("grid", payload)
        # Emit only after config and the global history have both been
        # updated. MainWindow uses this as the close-time flush ack.
        self.grid_layout_persisted.emit(True)
        return True

    @Slot(result=str)
    def reset_grid_layout(self):
        """Restore the default grid with every window visible."""
        payload = LayoutService.default_payload()
        self.ctx.config.set_state(
            grid_layout=payload,
            window_states={"closed": [], "minimized": []})
        self.ctx.undo.push("grid", payload)
        self.ctx.bus.emit(LogMessage(
            message="↺ Grid layout reset to default (all windows visible)",
            level="info"))
        return payload

    # ── window open/close/minimize states ────────────────────────
    @Slot(result=str)
    def get_window_states(self):
        raw = self.ctx.config.get_state("window_states", None)
        if isinstance(raw, dict):
            closed = raw.get("closed", [])
            minimized = raw.get("minimized", [])
            closed = [i for i in closed
                      if isinstance(i, str) and i in self.WINDOW_IDS]
            minimized = [i for i in minimized
                         if isinstance(i, str)
                         and i in self.WINDOW_IDS and i not in closed]
            return json.dumps({"closed": closed, "minimized": minimized},
                              ensure_ascii=False)
        return ""

    def _state_ids(self, data: dict, key: str) -> list:
        """The known window ids stored under one state key (non-list ⇒ [])."""
        raw = data.get(key, [])
        if not isinstance(raw, list):
            return []
        return [i for i in raw
                if isinstance(i, str) and i in self.WINDOW_IDS]

    @Slot(str, result=bool)
    def save_window_states(self, states_json):
        try:
            data = json.loads(states_json or "{}")
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict):
            return False
        closed = self._state_ids(data, "closed")
        minimized = [i for i in self._state_ids(data, "minimized")
                     if i not in closed]
        self.ctx.config.set_state(window_states={"closed": closed,
                                                 "minimized": minimized})
        return True

    @Slot(bool)
    def set_block_config_pinned(self, pinned):
        """Persist the Block Config keep-open pin across app restarts."""
        self.ctx.config.set_state(block_config_pinned=bool(pinned))

    # ── unified app state (session restore) ──────────────────────
    @Slot(result=str)
    def get_app_state(self):
        """Everything the UI needs to restore the last session in one
        payload."""
        from services.run import normalize_blocks
        undo = self.ctx.undo
        history, h_idx = undo.history()
        stack_history, stack_idx = undo.stack_projection()
        raw_last_stack = self.ctx.config.get_state("last_stack", None)
        last_stack = (normalize_blocks(raw_last_stack)
                      if isinstance(raw_last_stack, list) else raw_last_stack)
        payload = {
            "theme": str(self.ctx.config.get("ui", "theme",
                                             default="dark") or "dark"),
            "url_presets": self.ctx.config.bookmarks.all(),
            "labels": self.ctx.label_store().state(),
            "custom_blocks": self.ctx.config.blocks.all(),
            "stack_presets": self.ctx.presets.list_stacks(),
            "template_presets": self.ctx.presets.list_templates(),
            "state": {
                "last_url_preset":
                    self.ctx.config.get_state("last_url_preset", ""),
                "last_stack_preset":
                    self.ctx.config.get_state("last_stack_preset", ""),
                "last_stack": last_stack,
                # Legacy projection retained so older page bundles can
                # still start; new edits use the global fields below.
                "stack_history": stack_history,
                "stack_history_index": stack_idx,
                "undo_history": history,
                "undo_history_index": h_idx,
                "grid_layout": self.get_grid_layout() or None,
                "block_config_pinned":
                    self.ctx.config.get_state("block_config_pinned", False),
                "window_states":
                    self.ctx.config.get_state("window_states", None),
                "window_geometry":
                    self.ctx.config.get_state("window_geometry", None),
            },
        }
        return json.dumps(payload, ensure_ascii=False)
