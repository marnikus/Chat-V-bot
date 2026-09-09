"""Compatibility shim — the run engine lives in services/run/."""

from services.run import (  # noqa: F401
    RETIRED_BLOCK_KEYS,
    STANDALONE_NICK,
    USER_SCOPED_BLOCKS,
    RunHooks,
    RunProgress,
    RunProgressChanged,
    RunState,
    RunStateMachine,
    RunTracer,
    norm_level,
    normalize_blocks,
)
from actions.base_action import (  # noqa: F401
    BaseAction, ActionResult, get_action_class, all_action_ids,
)

__all__ = ["ActionEngine", "RunCoordinator", "RunHooks", "RunProgress",
           "RunProgressChanged", "RunState", "RunStateMachine",
           "RunTracer", "normalize_blocks", "norm_level",
           "USER_SCOPED_BLOCKS", "STANDALONE_NICK", "RETIRED_BLOCK_KEYS",
           "BaseAction", "ActionResult", "get_action_class",
           "all_action_ids"]


def __getattr__(name):
    if name in {"ActionEngine", "RunCoordinator"}:
        from services.run import ActionEngine, RunCoordinator
        return {"ActionEngine": ActionEngine,
                "RunCoordinator": RunCoordinator}[name]
    raise AttributeError(name)
