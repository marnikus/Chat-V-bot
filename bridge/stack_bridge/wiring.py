"""The stack bridge's plumbing: engine signals, preset events, scheduling.

`WiringMixin` owns everything that is not a slot: relaying the run
engine's signals onto the bridge's own (a duck-typed test engine
without Qt signals is simply not connected), turning a `PresetsChanged`
event into the matching list signal, the one log helper, the
schedule-or-close guard, and the retired-block-key strip every stored
stack goes through.
"""

from __future__ import annotations

import asyncio
import logging

from core.events import LogMessage
from services.run import normalize_blocks

log = logging.getLogger("chatbot")


class WiringMixin:
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

    def _log(self, message: str, level: str = "info") -> None:
        self.ctx.bus.emit(LogMessage(message=message, level=level))

    @staticmethod
    def _schedule(coro) -> None:
        try:
            asyncio.ensure_future(coro)
        except RuntimeError:
            coro.close()

    @staticmethod
    def _clean_blocks(blocks):
        """Strip retired block keys before storing or emitting a stack."""
        return normalize_blocks(blocks)
