"""Action registry — auto-registration via decorator + pkgutil scan.

Usage in each action module:

    from actions.registry import register

    @register("MY_BLOCK")
    class MyBlock(BaseAction):
        ...

No manual import list needed; `discover()` scans the package.

The registry itself lives in :mod:`actions.base_action` (next to the
`__init_subclass__` hook that fills it) and is re-exported here, so the
decorator path and the subclass path always fill ONE palette.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass

from backend.cdp_client import CDPClient

# Single source of truth - do NOT create a second dict here (BUG-01: the old
# private _REGISTRY in this module was only ever fed by @register, which no
# block uses, so actions.all_action_ids() returned [] while 15 blocks were
# live in actions.base_action._REGISTRY).
from actions.base_action import (  # noqa: F401
    _REGISTRY,
    all_action_ids,
    get_action_class,
    register,
)

log = logging.getLogger("chatbot")


@dataclass
class ActionContext:
    """Per-execution context passed to actions (replaces ad-hoc kwargs)."""

    cdp: CDPClient
    memory: object | None = None
    criteria: object | None = None
    engine: object | None = None
    user_nick: str = ""


def discover(package: str = "actions") -> int:
    """Import all modules in `package` so @register decorators fire.

    Returns number of newly discovered block ids. A module that fails to
    import is logged, never swallowed: a block silently vanishing from the
    palette is exactly how a broken action hides from the user.
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
        except Exception as exc:  # noqa: BLE001
            log.warning("Action module %s failed to import - its block(s) "
                        "are unavailable: %s", name, exc)
            continue
    return len(_REGISTRY) - before


# Auto-scan on import so get_action_class works without explicit discover()
try:
    discover()
except Exception:  # noqa: BLE001
    pass
