"""Stack bridge run control — extracted from stack_bridge_parts (H-C5 split)

Run/stop/pause, ≤120 LOC.
"""

from __future__ import annotations

import asyncio
import json
import logging

from core.events import LogMessage
from services.run import normalize_blocks

log = logging.getLogger("chatbot")


def clean_blocks(blocks):
    return normalize_blocks(blocks)


def schedule(coro) -> None:
    try:
        asyncio.ensure_future(coro)
    except RuntimeError:
        coro.close()


class _Part:
    def __init__(self, host):
        self._host = host
        self._ctx = host.ctx

    def _log(self, message: str, level: str = "info") -> None:
        self._host._log(message, level)


class RunControl(_Part):
    def connect_engine(self, engine) -> None:
        host = self._host
        try:
            engine.step_complete.connect(host.step_complete.emit)
            engine.step_started.connect(host.step_started.emit)
            engine.stack_complete.connect(host.stack_complete.emit)
            engine.log_msg.connect(lambda m: self._ctx.bus.emit(LogMessage(message=m, level="info")))
            engine.debug_msg.connect(lambda m, l: self._ctx.bus.emit(LogMessage(message=m, level=l)))
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
            self._log("❌ Stack is not a list of blocks", "error")
            return
        blocks = clean_blocks(blocks)
        engine.load_stack(blocks)
        self._ctx.config.set_state(last_stack=blocks, last_stack_preset="")
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
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return
        if not isinstance(blocks, list):
            return
        self._ctx.config.set_state(last_stack=clean_blocks(blocks), last_stack_preset="")
