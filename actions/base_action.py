"""Abstract base class for all action blocks."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional
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

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.block_id:
            _REGISTRY[cls.block_id] = cls

    @abstractmethod
    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        """Run this action. Return ActionResult.*

        :param engine: the running ActionEngine (optional). When provided,
            actions stream step-by-step debugger detail through
            ``engine.report(message, level)`` so every element search,
            clickability check and outcome is visible in the log console
            and written to the run trace.
        """
        ...

    async def pre_delay(self) -> None:
        if self.pre_delay_ms > 0:
            await asyncio.sleep(self.pre_delay_ms / 1000.0)

    def config_schema(self) -> dict:
        return {"pre_delay_ms": {"type": "number", "default": 500, "label": "Pre-delay (ms)"}}

    @property
    def display_name(self) -> str:
        """Name shown in the stack/logs: custom block name if set."""
        custom = getattr(self, "custom_name", None)
        if isinstance(custom, str) and custom.strip():
            return custom.strip()
        return self.name

    def to_dict(self) -> dict:
        """Serialize the block with ALL of its settings (round-trip safe)."""
        d: dict[str, Any] = {"block_id": self.block_id}
        for key, value in vars(self).items():
            if key.startswith("_") or key in ("config", "pre_delay_ms"):
                continue
            d[key] = value
        d["pre_delay_ms"] = getattr(self, "pre_delay_ms", 500)
        if self.config:
            d.update(self.config)
        return d


def get_action_class(block_id: str) -> Optional[type]:
    return _REGISTRY.get(block_id)


def all_action_ids() -> list[str]:
    return list(_REGISTRY.keys())
