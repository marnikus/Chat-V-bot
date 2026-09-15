"""The domain parts of `StackBridge` (G7 §4, the cohesion pass).

The bridge keeps its entire wire surface — the eight Signals and the
twenty-one @Slots, every name and signature unchanged — and delegates each
body here. Parts emit Qt signals *through the host QObject*, so signal
identity (and every QML connection) survives the move untouched.

One bundle field (`bridge._parts`) is what every delegate touches; that is
also the LCOM* story — the old class scored 0.89 because thirty-one methods
each owned a private slice of state, while now the bridge methods share one
field and the domain state lives in five small classes of 4–7 methods.
"""

from __future__ import annotations

import asyncio
import json
import logging

from core.events import LogMessage, PresetsChanged
from services.run import normalize_blocks

log = logging.getLogger("chatbot")


def clean_blocks(blocks):
    """Strip retired block keys before storing or emitting a stack."""
    return normalize_blocks(blocks)


def schedule(coro) -> None:
    """Run `coro` on the app loop; close it cleanly when there is none."""
    try:
        asyncio.ensure_future(coro)
    except RuntimeError:
        coro.close()


class _Part:
    """Shared plumbing: the host bridge (signals + logging) and its ctx."""

    def __init__(self, host):
        self._host = host
        self._ctx = host.ctx

    def _log(self, message: str, level: str = "info") -> None:
        self._host._log(message, level)


class RunControl(_Part):
    """Run/stop/pause plus the engine signal wiring and stack snapshots."""

    def connect_engine(self, engine) -> None:
        """Connect the engine's run signals; a duck-typed test engine
        without Qt signals is simply not connected."""
        host = self._host
        try:
            engine.step_complete.connect(host.step_complete.emit)
            engine.step_started.connect(host.step_started.emit)
            engine.stack_complete.connect(host.stack_complete.emit)
            engine.log_msg.connect(lambda m: self._ctx.bus.emit(
                LogMessage(message=m, level="info")))
            engine.debug_msg.connect(lambda m, l: self._ctx.bus.emit(
                LogMessage(message=m, level=l)))
        except (AttributeError, TypeError) as exc:
            log.debug("engine run signals not connected: %s", exc)

    def run_stack(self, stack_json):
        engine = self._ctx.engine
        if engine.is_running:
            self._log("⚠ Already running", "warn")
            return
        try:
            blocks = json.loads(stack_json)
        except json.JSONDecodeError:
            self._log("❌ Bad JSON", "error")
            return
        if not isinstance(blocks, list):
            # Wrong-shaped JSON must not execute anything or touch config
            # (a dict/string/number used to reach normalize_blocks, which
            # silently ran an empty stack or raised TypeError on numbers).
            self._log("❌ Stack is not a list of blocks", "error")
            return
        blocks = clean_blocks(blocks)
        engine.load_stack(blocks)
        self._ctx.config.set_state(last_stack=blocks,
                                   last_stack_preset="")
        schedule(engine.execute())

    def stop(self) -> None:
        self._ctx.engine.stop()

    def pause(self) -> None:
        self._ctx.engine.pause()

    def resume(self) -> None:
        self._ctx.engine.resume()

    def current_json(self) -> str:
        return json.dumps(self._ctx.engine.get_stack(), ensure_ascii=False)

    def snapshot(self, stack_json) -> None:
        """Persist the current stack for the next session (debounced)."""
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return
        if not isinstance(blocks, list):
            return
        # App.recordGlobal() already recorded the edit; this is only the
        # last-session snapshot and must not create a second entry.
        self._ctx.config.set_state(last_stack=clean_blocks(blocks),
                                   last_stack_preset="")


class Composer(_Part):
    """The message composer draft and the criteria pane."""

    def __init__(self, host):
        super().__init__(host)
        self._message_text = ""

    def save_message(self, text) -> None:
        self._message_text = text
        try:
            self._ctx.engine.composer_text = text
        except Exception:                               # noqa: BLE001
            pass

    def get_message(self) -> str:
        return self._message_text

    def save_criteria(self, j) -> None:
        self._ctx.criteria.load_json(j)
        self._log("💾 Criteria saved", "info")

    def get_criteria(self) -> str:
        return self._ctx.criteria.to_json()


class StackPresets(_Part):
    """Save/load/list/delete for stack presets (the preset chips)."""

    def _remember(self, name: str, blocks: list[dict]) -> None:
        self._ctx.config.set_state(last_stack=blocks, last_stack_preset=name)
        self._ctx.undo.push_stack(blocks)

    def _emit(self) -> None:
        payload = json.dumps(self._ctx.presets.list_stacks(),
                             ensure_ascii=False)
        self._host.preset_list_updated.emit(payload)
        self._ctx.bus.emit(PresetsChanged(kind="stacks", payload=payload))

    def save(self, name, stack_json) -> None:
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            self._log("❌ Preset save aborted: stack is not valid JSON",
                      "error")
            return
        if not isinstance(blocks, list):
            self._log("❌ Preset save aborted: bad stack payload", "error")
            return
        blocks = clean_blocks(blocks)
        try:
            self._ctx.presets.save_stack(name, blocks)
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Preset save failed: {exc}", "error")
            return
        try:
            self._ctx.presets.save(force=True)
        except Exception:
            pass
        self._remember(name, blocks)
        self._emit()
        self._log(
            f"💾 Preset “{name}” saved ({len(blocks)} block(s)) — reload "
            f"anytime from the preset chips", "success")

    def load(self, name) -> str:
        blocks = self._ctx.presets.load_stack(name)
        if blocks is None:
            self._log(f"❌ Preset “{name}” not found", "error")
            return "null"
        blocks = clean_blocks(blocks)
        # Preserve current stack in history before overwriting
        try:
            current = self._ctx.config.get_state("last_stack", None)
            if isinstance(current, list) and current:
                if current != blocks:
                    self._ctx.undo.push_stack(current)
        except Exception:                               # noqa: BLE001
            pass
        self._ctx.engine.load_stack(blocks)
        self._remember(name, blocks)
        payload = json.dumps(blocks, ensure_ascii=False)
        self._host.stack_loaded.emit(name, payload)
        self._log(f"📂 Preset “{name}” loaded — {len(blocks)} block(s) "
                  "restored (↩ Undo to return to previous)", "success")
        return payload

    def list_json(self) -> str:
        try:
            return json.dumps(self._ctx.presets.list_stacks(),
                              ensure_ascii=False)
        except Exception as exc:                        # noqa: BLE001
            log.error("list presets failed: %s", exc)
            return "[]"

    def delete(self, name) -> None:
        try:
            if self._ctx.presets.delete_stack(name):
                self._emit()
                self._log(f"🗑 Preset “{name}” deleted", "warn")
            else:
                self._log(f"⚠ Preset “{name}” not found", "warn")
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Preset delete failed: {exc}", "error")


class TemplatePresets(_Part):
    """Save/load/list/delete for message template presets."""

    def _emit(self) -> None:
        payload = json.dumps(self._ctx.presets.list_templates(),
                             ensure_ascii=False)
        self._host.template_list_updated.emit(payload)
        self._ctx.bus.emit(PresetsChanged(kind="templates", payload=payload))

    def save(self, name, body) -> None:
        try:
            self._ctx.presets.save_template(name, body or "")
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Template save failed: {exc}", "error")
            return
        self._emit()
        self._log(f"💾 Template “{name}” saved", "success")

    def load(self, name) -> str:
        body = self._ctx.presets.load_template(name)
        if body is None:
            self._log(f"❌ Template “{name}” not found", "error")
            return ""
        self._host.template_loaded.emit(name, body)
        self._log(f"📂 Template “{name}” loaded", "success")
        return body

    def list_json(self) -> str:
        try:
            return json.dumps(self._ctx.presets.list_templates(),
                              ensure_ascii=False)
        except Exception as exc:                        # noqa: BLE001
            log.error("list templates failed: %s", exc)
            return "[]"

    def delete(self, name) -> None:
        try:
            if self._ctx.presets.delete_template(name):
                self._emit()
                self._log(f"🗑 Template “{name}” deleted", "warn")
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Template delete failed: {exc}", "error")


class CustomBlocks(_Part):
    """Save/list/delete for custom Find & Click block presets."""

    def _emit(self) -> None:
        payload = json.dumps(self._ctx.config.blocks.all(),
                             ensure_ascii=False)
        self._host.custom_blocks_updated.emit(payload)
        self._ctx.bus.emit(PresetsChanged(kind="custom_blocks",
                                          payload=payload))

    def list_json(self) -> str:
        return json.dumps(self._ctx.config.blocks.all(), ensure_ascii=False)

    def save(self, name, block_json) -> None:
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
        result = self._ctx.config.blocks.save_custom_block(name, block)
        if result.is_err:
            err_ = result.err()
            self._log(f"❌ Block preset save failed: "
                      f"{err_.detail or err_.code}", "error")
            return
        self._ctx.config.save()
        self._emit()
        self._log(f"💾 Block preset “{name}” saved — reusable from "
                  "the + Add menu and Custom Blocks chips", "success")

    def delete(self, name) -> None:
        before = len(self._ctx.config.blocks.all())
        self._ctx.config.blocks.delete_custom_block(name)
        if len(self._ctx.config.blocks.all()) != before:
            self._ctx.config.save()
            self._emit()
            self._log(f"🗑 Block preset “{name}” removed", "warn")
        else:
            self._log(f"⚠ Block preset “{name}” not found", "warn")


class StackBridgeParts:
    """The five domains, created together (each is a trivial host-holder).

    `on_presets` is the bus subscriber the bridge registers: it dispatches
    a `PresetsChanged` event to the matching host signal.
    """

    def __init__(self, host):
        self._host = host
        self.run = RunControl(host)
        self.composer = Composer(host)
        self.presets = StackPresets(host)
        self.templates = TemplatePresets(host)
        self.blocks = CustomBlocks(host)

    def on_presets(self, event) -> None:
        host = self._host
        if event.kind == "stacks":
            host.preset_list_updated.emit(event.payload or "[]")
        elif event.kind == "templates":
            host.template_list_updated.emit(event.payload or "[]")
        elif event.kind == "custom_blocks":
            host.custom_blocks_updated.emit(event.payload or "[]")
