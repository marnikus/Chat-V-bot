"""Action block registry: type -> executor instance.

`register` must be defined before the executor modules are imported at the
bottom of this file (they import `register` from here).
"""
from __future__ import annotations

from .base import BaseExecutor

_REGISTRY: dict[str, BaseExecutor] = {}


def register(cls: type[BaseExecutor]) -> type[BaseExecutor]:
    _REGISTRY[cls.action_type] = cls()
    return cls


def get(action_type: str) -> BaseExecutor | None:
    return _REGISTRY.get(action_type)


def all_types() -> list[str]:
    return list(_REGISTRY)


def schemas() -> dict[str, dict]:
    """action_type -> {icon, label, params[]} for the GUI palette/builder."""
    return {k: {"icon": v.icon, "label": v.label, "params": v.params_schema}
            for k, v in _REGISTRY.items()}


# --- executor imports (trigger registration) — keep last -------------------
from . import (attach_image, click_user, close_tab, condition, go_main_tab,  # noqa: E402,F401
               loop_marker, pick_target, scroll_parse, send_message,
               type_message, wait_sleep)  # noqa: E402
