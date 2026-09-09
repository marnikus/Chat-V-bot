"""BaseAction — the abstract interface every action block implements.

The registry (actions/registry.py) and the run-time context
(actions/context.py) used to live here with it; they are separate modules
now, so this file is interface-only.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

log = logging.getLogger("chatbot")


class ActionResult:
    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"


class BaseAction(ABC):
    """Every action block inherits this and implements execute()."""
    block_id: str = ""
    name: str = ""
    icon: str = ""

    def __init__(self, pre_delay_ms: int = 500, enabled: bool = True, **kwargs):
        # 'enabled' and 'pre_delay_ms' may arrive inside kwargs when built
        # from dict (load_stack)
        if "enabled" in kwargs:
            enabled = kwargs.pop("enabled")
        if "pre_delay_ms" in kwargs:
            pre_delay_ms = kwargs.pop("pre_delay_ms")
        self.pre_delay_ms = pre_delay_ms
        self.enabled = bool(enabled) if enabled is not None else True
        self.config = kwargs

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Self-registration: defining a subclass with a block_id IS the
        # registration. (The explicit @ActionRegistry.register decorator
        # exists for aliases and non-inheriting adapters.)
        if cls.block_id:
            from actions.registry import ActionRegistry
            ActionRegistry.register_class(cls)

    @abstractmethod
    async def execute(self, user_nick: str, cdp,
                      engine: Optional[object] = None) -> str:
        """Run this action. Return ActionResult.*

        :param engine: the run context (an ActionContext built by the run
            service, duck-compatible with the historical ActionEngine
            surface). When provided, actions stream step-by-step debugger
            detail through ``engine.report(message, level)`` so every
            element search, clickability check and outcome is visible in
            the log console and written to the run trace.
        """
        ...

    async def pre_delay(self) -> None:
        if self.pre_delay_ms > 0:
            await asyncio.sleep(self.pre_delay_ms / 1000.0)

    def config_schema(self) -> dict:
        return {"pre_delay_ms": {"type": "number", "default": 500,
                                 "label": "Pre-delay (ms)"}}

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
            if key.startswith("_") or key in ("config", "pre_delay_ms",
                                              "enabled"):
                continue
            d[key] = value
        d["pre_delay_ms"] = getattr(self, "pre_delay_ms", 500)
        d["enabled"] = getattr(self, "enabled", True)
        if self.config:
            d.update(self.config)
        return d
