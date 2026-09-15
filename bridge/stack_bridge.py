"""StackBridge — the QML wire surface of the action-stack domain.

@Slot methods for the action-stack domain. Runs go through the engine
(services/run_service.py); stack/template presets through the preset
store; custom Find & Click blocks through the block store.

G7 §4 (the cohesion pass): this file is now only the wire — the eight
Signals and the twenty-one @Slots, every name and signature unchanged,
each body a one-line delegate into `bridge/stack_bridge_parts.py`. The
parts emit signals through this QObject, so every QML connection and
every test pin on the bridge surface behaves exactly as before; LCOM*
dropped from 0.89 because the domain state moved out of the class.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from bridge.stack_bridge_parts import StackBridgeParts, clean_blocks, schedule
from core.events import LogMessage, PresetsChanged, StackLoaded

log = logging.getLogger("chatbot")


class StackBridge(QObject):
    step_complete = Signal(str, str)
    step_started = Signal(int, str, str)     # index, block_id, user_nick
    stack_complete = Signal()
    preset_list_updated = Signal(str)        # JSON: stack presets
    template_list_updated = Signal(str)      # JSON: template presets
    custom_blocks_updated = Signal(str)      # JSON: custom block presets
    template_loaded = Signal(str, str)       # name, body
    stack_loaded = Signal(str, str)          # name, JSON blocks

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._parts = StackBridgeParts(self)
        ctx.bus.subscribe(PresetsChanged, self._parts.on_presets)
        ctx.bus.subscribe(StackLoaded,
                          lambda e: self.stack_loaded.emit(e.name, e.payload))
        engine = ctx.engine
        if engine is not None:
            self._parts.run.connect_engine(engine)

    def _log(self, message: str, level: str = "info") -> None:
        self.ctx.bus.emit(LogMessage(message=message, level=level))

    # Test pins: the two static helpers stay reachable under the bridge
    # name — test_stack_commands.py calls `StackBridge._schedule` and
    # test_grid_persistence.py calls `bridge._clean_blocks` (G7 §4).
    _clean_blocks = staticmethod(clean_blocks)
    _schedule = staticmethod(schedule)

    # ── run / pause / stop ───────────────────────────────────────
    @Slot(str)
    def run_stack(self, stack_json):
        self._parts.run.run_stack(stack_json)

    @Slot()
    def stop_stack(self):
        self._parts.run.stop()

    @Slot()
    def pause_stack(self):
        self._parts.run.pause()

    @Slot()
    def resume_stack(self):
        self._parts.run.resume()

    # ── message composer ─────────────────────────────────────────
    @Slot(str)
    def save_message(self, text):
        self._parts.composer.save_message(text)

    @Slot(result=str)
    def get_message(self):
        return self._parts.composer.get_message()

    # ── criteria ─────────────────────────────────────────────────
    @Slot(str)
    def save_criteria(self, j):
        self._parts.composer.save_criteria(j)

    @Slot(result=str)
    def get_criteria(self):
        return self._parts.composer.get_criteria()

    # ── stack presets ────────────────────────────────────────────
    @Slot(str, str)
    def save_stack_preset(self, name, stack_json):
        self._parts.presets.save(name, stack_json)

    @Slot(str, result=str)
    def load_stack_preset(self, name):
        return self._parts.presets.load(name)

    @Slot(result=str)
    def list_stack_presets(self):
        return self._parts.presets.list_json()

    @Slot(str)
    def delete_stack_preset(self, name):
        self._parts.presets.delete(name)

    # ── message template presets ─────────────────────────────────
    @Slot(str, str)
    def save_template_preset(self, name, body):
        self._parts.templates.save(name, body)

    @Slot(str, result=str)
    def load_template_preset(self, name):
        return self._parts.templates.load(name)

    @Slot(result=str)
    def list_template_presets(self):
        return self._parts.templates.list_json()

    @Slot(str)
    def delete_template_preset(self, name):
        self._parts.templates.delete(name)

    # ── custom Find & Click block presets ────────────────────────
    @Slot(result=str)
    def list_custom_blocks(self):
        return self._parts.blocks.list_json()

    @Slot(str, str)
    def save_custom_block(self, name, block_json):
        self._parts.blocks.save(name, block_json)

    @Slot(str)
    def delete_custom_block(self, name):
        self._parts.blocks.delete(name)

    # ── engine current stack (compat helper) ─────────────────────
    @Slot(result=str)
    def get_stack_json(self):
        return self._parts.run.current_json()

    # ── last-session stack snapshot ──────────────────────────────
    @Slot(str)
    def snapshot_stack(self, stack_json):
        """Persist the current stack for the next session (debounced)."""
        self._parts.run.snapshot(stack_json)
