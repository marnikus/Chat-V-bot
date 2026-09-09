"""Compatibility shim — BaseAction lives in actions/base.py, the registry
in actions/registry.py, the run context in actions/context.py."""

from actions.base import BaseAction, ActionResult  # noqa: F401
from actions.registry import (  # noqa: F401
    ActionRegistry, get_action_class, all_action_ids,
)

__all__ = ["BaseAction", "ActionResult", "ActionRegistry",
           "get_action_class", "all_action_ids"]
