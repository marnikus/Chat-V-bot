from .hooks import (RETIRED_BLOCK_KEYS, STANDALONE_NICK, USER_SCOPED_BLOCKS,
                    RunHooks, RunTracer, norm_level, normalize_blocks)
from .progress import RunProgress, RunProgressChanged
from .state_machine import RunState, RunStateMachine

__all__ = [
    "ActionEngine", "RunCoordinator", "RetryPolicy", "RunHooks",
    "RunProgress", "RunProgressChanged", "RunState", "RunStateMachine",
    "RunTracer", "normalize_blocks", "norm_level", "USER_SCOPED_BLOCKS",
    "STANDALONE_NICK", "RETIRED_BLOCK_KEYS",
]


def __getattr__(name):
    if name in {"ActionEngine", "RunCoordinator"}:
        from .coordinator import ActionEngine, RunCoordinator
        return {"ActionEngine": ActionEngine,
                "RunCoordinator": RunCoordinator}[name]
    if name == "RetryPolicy":
        from .error_recovery import RetryPolicy
        return RetryPolicy
    raise AttributeError(name)
