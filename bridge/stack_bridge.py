"""StackBridge — run control, presets, composer, criteria.

@Slot methods for the action-stack domain. Runs go through the engine
(services/run_service.py); stack/template presets through the preset
store; custom Find & Click blocks through the block store.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from PySide6.QtCore import QObject, Signal, Slot

from core.events import (LogMessage, PresetsChanged, StackLoaded)
from services.run_service import normalize_blocks

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
        self._message_text = ""
        ctx.bus.subscribe(PresetsChanged, self._on_presets)
        ctx.bus.subscribe(StackLoaded,
                          lambda e: self.stack_loaded.emit(e.name, e.payload))
        engine = ctx.engine
        if engine is not None:
            self._connect_engine(engine)

    def _connect_engine(self, engine) -> None:
        """Connect the engine's run signals; a duck-typed test engine
        without Qt signals is simply not connected."""
        try:
            engine.step_complete.connect(self.step_complete.emit)
            engine.step_started.connect(self.step_started.emit)
            engine.stack_complete.connect(self.stack_complete.emit)
            engine.log_msg.connect(lambda m: self.ctx.bus.emit(
                LogMessage(message=m, level="info")))
            engine.debug_msg.connect(lambda m, l: self.ctx.bus.emit(
                LogMessage(message=m, level=l)))
        except (AttributeError, TypeError) as exc:
            log.debug("engine run signals not connected: %s", exc)

    def _on_presets(self, event) -> None:
        if event.kind == "stacks":
            self.preset_list_updated.emit(event.payload or "[]")
        elif event.kind == "templates":
            self.template_list_updated.emit(event.payload or "[]")
        elif event.kind == "custom_blocks":
            self.custom_blocks_updated.emit(event.payload or "[]")

    @staticmethod
    def _clean_blocks(blocks):
        """Strip retired block keys before storing or emitting a stack."""
        return normalize_blocks(blocks)

    def _log(self, message: str, level: str = "info") -> None:
        self.ctx.bus.emit(LogMessage(message=message, level=level))

    # ── run / pause / stop ───────────────────────────────────────
    @Slot(str)
    def run_stack(self, stack_json):
        engine = self.ctx.engine
        if engine.is_running:
            self._log("⚠ Already running", "warn")
            return
        try:
            blocks = json.loads(stack_json)
        except json.JSONDecodeError:
            self._log("❌ Bad JSON", "error")
            return
        blocks = self._clean_blocks(blocks)
        engine.load_stack(blocks)
        if isinstance(blocks, list):
            self.ctx.config.set_state(last_stack=blocks,
                                      last_stack_preset="")
        self._schedule(engine.execute())

    @Slot()
    def stop_stack(self):
        self.ctx.engine.stop()

    @Slot()
    def pause_stack(self):
        self.ctx.engine.pause()

    @Slot()
    def resume_stack(self):
        self.ctx.engine.resume()

    @staticmethod
    def _schedule(coro) -> None:
        try:
            asyncio.ensure_future(coro)
        except RuntimeError:
            coro.close()

    # ── message composer ─────────────────────────────────────────
    @Slot(str)
    def save_message(self, text):
        self._message_text = text
        try:
            self.ctx.engine.composer_text = text
        except Exception:                               # noqa: BLE001
            pass

    @Slot(result=str)
    def get_message(self):
        return self._message_text

    # ── criteria ─────────────────────────────────────────────────
    @Slot(str)
    def save_criteria(self, j):
        self.ctx.criteria.load_json(j)
        self._log("💾 Criteria saved", "info")

    @Slot(result=str)
    def get_criteria(self):
        return self.ctx.criteria.to_json()

    # ── stack presets ────────────────────────────────────────────
    def _remember_stack(self, name: str, blocks: list[dict]) -> None:
        self.ctx.config.set_state(last_stack=blocks, last_stack_preset=name)
        self.ctx.undo.push_stack(blocks)

    def _emit_presets(self) -> None:
        try:
            self.ctx.presets.load()
        except Exception:
            pass
        payload = json.dumps(self.ctx.presets.list_stacks(),
                             ensure_ascii=False)
        self.preset_list_updated.emit(payload)
        self.ctx.bus.emit(PresetsChanged(kind="stacks", payload=payload))

    @Slot(str, str)
    def save_stack_preset(self, name, stack_json):
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            self._log("❌ Preset save aborted: stack is not valid JSON",
                      "error")
            return
        if not isinstance(blocks, list):
            self._log("❌ Preset save aborted: bad stack payload", "error")
            return
        blocks = self._clean_blocks(blocks)
        try:
            self.ctx.presets.save_stack(name, blocks)
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Preset save failed: {exc}", "error")
            return
        self._remember_stack(name, blocks)
        self._emit_presets()
        self._log(
            f"💾 Preset “{name}” saved ({len(blocks)} block(s)) — reload "
            f"anytime from the preset chips", "success")

    @Slot(str, result=str)
    def load_stack_preset(self, name):
        blocks = self.ctx.presets.load_stack(name)
        if blocks is None:
            self._log(f"❌ Preset “{name}” not found", "error")
            return "null"
        blocks = self._clean_blocks(blocks)
        # Preserve current stack in history before overwriting
        try:
            current = self.ctx.config.get_state("last_stack", None)
            if isinstance(current, list) and current:
                if current != blocks:
                    self.ctx.undo.push_stack(current)
        except Exception:                               # noqa: BLE001
            pass
        self.ctx.engine.load_stack(blocks)
        self._remember_stack(name, blocks)
        payload = json.dumps(blocks, ensure_ascii=False)
        self.stack_loaded.emit(name, payload)
        self._log(f"📂 Preset “{name}” loaded — {len(blocks)} block(s) "
                  "restored (↩ Undo to return to previous)", "success")
        return payload

    @Slot(result=str)
    def list_stack_presets(self):
        try:
            # Ensure fresh data from disk — preset save may occur via
            # another process or bridge instance (BUG #1 visibility fix).
            self.ctx.presets.load()
            return json.dumps(self.ctx.presets.list_stacks(),
                              ensure_ascii=False)
        except Exception as exc:                        # noqa: BLE001
            log.error("list presets failed: %s", exc)
            return "[]"

    @Slot(str)
    def delete_stack_preset(self, name):
        try:
            if self.ctx.presets.delete_stack(name):
                self._emit_presets()
                self._log(f"🗑 Preset “{name}” deleted", "warn")
            else:
                self._log(f"⚠ Preset “{name}” not found", "warn")
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Preset delete failed: {exc}", "error")

    # ── message template presets ─────────────────────────────────
    def _emit_templates(self) -> None:
        payload = json.dumps(self.ctx.presets.list_templates(),
                             ensure_ascii=False)
        self.template_list_updated.emit(payload)
        self.ctx.bus.emit(PresetsChanged(kind="templates", payload=payload))

    @Slot(str, str)
    def save_template_preset(self, name, body):
        try:
            self.ctx.presets.save_template(name, body or "")
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Template save failed: {exc}", "error")
            return
        self._emit_templates()
        self._log(f"💾 Template “{name}” saved", "success")

    @Slot(str, result=str)
    def load_template_preset(self, name):
        body = self.ctx.presets.load_template(name)
        if body is None:
            self._log(f"❌ Template “{name}” not found", "error")
            return ""
        self.template_loaded.emit(name, body)
        self._log(f"📂 Template “{name}” loaded", "success")
        return body

    @Slot(result=str)
    def list_template_presets(self):
        try:
            return json.dumps(self.ctx.presets.list_templates(),
                              ensure_ascii=False)
        except Exception as exc:                        # noqa: BLE001
            log.error("list templates failed: %s", exc)
            return "[]"

    @Slot(str)
    def delete_template_preset(self, name):
        try:
            if self.ctx.presets.delete_template(name):
                self._emit_templates()
                self._log(f"🗑 Template “{name}” deleted", "warn")
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Template delete failed: {exc}", "error")

    # ── custom Find & Click block presets ────────────────────────
    def _emit_blocks(self) -> None:
        payload = json.dumps(self.ctx.config.blocks.all(),
                             ensure_ascii=False)
        self.custom_blocks_updated.emit(payload)
        self.ctx.bus.emit(PresetsChanged(kind="custom_blocks",
                                         payload=payload))

    @Slot(result=str)
    def list_custom_blocks(self):
        return json.dumps(self.ctx.config.blocks.all(), ensure_ascii=False)

    @Slot(str, str)
    def save_custom_block(self, name, block_json):
        name = (name or "").strip()
        try:
            block = json.loads(block_json or "{}")
        except json.JSONDecodeError:
            self._log("❌ Block preset save aborted: bad JSON", "error")
            return
        if not isinstance(block, dict) or not name:
            self._log("❌ Block preset needs a name and block config",
                      "error")
            return
        self.ctx.config.blocks.save_block(name, block)
        self.ctx.config.save()
        self._emit_blocks()
        self._log(f"💾 Block preset “{name}” saved — reusable from "
                  "the + Add menu and Custom Blocks chips", "success")

    @Slot(str)
    def delete_custom_block(self, name):
        before = len(self.ctx.config.blocks.all())
        self.ctx.config.blocks.delete(name)
        if len(self.ctx.config.blocks.all()) != before:
            self.ctx.config.save()
            self._emit_blocks()
            self._log(f"🗑 Block preset “{name}” removed", "warn")
        else:
            self._log(f"⚠ Block preset “{name}” not found", "warn")

    # ── engine current stack (compat helper) ─────────────────────
    @Slot(result=str)
    def get_stack_json(self):
        return json.dumps(self.ctx.engine.get_stack(), ensure_ascii=False)

    # ── last-session stack snapshot ──────────────────────────────
    @Slot(str)
    def snapshot_stack(self, stack_json):
        """Persist the current stack for the next session (debounced)."""
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return
        if not isinstance(blocks, list):
            return
        # App.recordGlobal() already recorded the edit; this is only the
        # last-session snapshot and must not create a second entry.
        self.ctx.config.set_state(last_stack=self._clean_blocks(blocks),
                                  last_stack_preset="")
