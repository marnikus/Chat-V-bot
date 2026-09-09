"""Action registry — auto-registration via decorator + pkgutil scan.

Usage in each action module:

    from actions.registry import register

    @register("MY_BLOCK")
    class MyBlock(BaseAction):
        ...

No manual import list needed; `discover()` scans the package.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Dict, Type, Optional

from backend.cdp_client import CDPClient

_REGISTRY: Dict[str, type] = {}


@dataclass
class ActionContext:
    """Per-execution context passed to actions (replaces ad-hoc kwargs)."""

    cdp: CDPClient
    memory: object | None = None
    criteria: object | None = None
    engine: object | None = None
    user_nick: str = ""


def register(block_id: str):
    """Decorator: @register(\"BLOCK_ID\") registers the action class."""

    def decorator(cls: type) -> type:
        if not block_id:
            raise ValueError("register: block_id must be non-empty")
        _REGISTRY[block_id] = cls
        cls.block_id = block_id  # type: ignore[attr-defined]
        return cls

    return decorator


def get_action_class(block_id: str) -> Optional[type]:
    return _REGISTRY.get(block_id)


def all_action_ids() -> list[str]:
    return list(_REGISTRY.keys())


def discover(package: str = "actions") -> int:
    """Import all modules in `package` so @register decorators fire.

    Returns number of newly discovered block ids.
    """
    before = len(_REGISTRY)
    try:
        pkg = importlib.import_module(package)
    except ImportError:
        return 0
    for mod in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
        name = mod.name
        if name.endswith(".registry") or name.endswith(".base_action"):
            continue
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001
            continue
    return len(_REGISTRY) - before


# Auto-scan on import so get_action_class works without explicit discover()
try:
    discover()
except Exception:  # noqa: BLE001
    pass
