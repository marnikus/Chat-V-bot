"""Abstract base class for all action blocks."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")

# Registry of all action classes keyed by block_id
_REGISTRY: dict[str, type] = {}


class ActionResult:
    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"


class BaseAction(ABC):
    """Every action block inherits this and implements execute()."""
    block_id: str = ""
    name: str = ""
    icon: str = ""

    def __init__(self, pre_delay_ms: int = 500, **kwargs):
        self.pre_delay_ms = pre_delay_ms
        self.config = kwargs
        self._debug_cb: Optional[Callable[[str], None]] = None
        self._debug_lines: list[str] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.block_id:
            _REGISTRY[cls.block_id] = cls

    @abstractmethod
    async def execute(self, user_nick: str, cdp: CDPClient) -> str:
        """Run this action. Return ActionResult.*"""
        ...

    async def pre_delay(self) -> None:
        if self.pre_delay_ms > 0:
            await asyncio.sleep(self.pre_delay_ms / 1000.0)

    # ── debugger support (per-step visibility) ────────────────────
    def set_debug_cb(self, cb: Optional[Callable[[str], None]] = None) -> None:
        """Attach a callback (usually the UI log signal) used by this block."""
        self._debug_cb = cb
        self._debug_lines = []

    def debug(self, message: str) -> None:
        """Emit a human-readable debug line for the current step."""
        self._debug_lines.append(message)
        if self._debug_cb:
            try:
                self._debug_cb(message)
            except Exception:
                pass
        log.debug(message)

    def debug_lines(self) -> list[str]:
        return list(self._debug_lines)

    def config_schema(self) -> dict:
        return {"pre_delay_ms": {"type": "number", "default": 500, "label": "Pre-delay (ms)"}}

    def to_dict(self) -> dict:
        return {"block_id": self.block_id, "pre_delay_ms": self.pre_delay_ms, **self.config}


def get_action_class(block_id: str) -> Optional[type]:
    return _REGISTRY.get(block_id)


def all_action_ids() -> list[str]:
    return list(_REGISTRY.keys())
