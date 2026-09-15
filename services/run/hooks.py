"""Run hooks — facade (H-C5 split)

Now ≤100 LOC via levels/tracer/mixin split.
"""

from __future__ import annotations

from services.run.hooks_levels import (
    RETIRED_BLOCK_KEYS,
    STANDALONE_NICK,
    USER_SCOPED_BLOCKS,
    maybe_await,
    norm_level,
    normalize_blocks,
)
from services.run.hooks_mixin import RunHooksMixin
from services.run.hooks_tracer import RunTracer


class RunHooks:
    def pre_run(self, coordinator) -> None:
        return None

    def post_run(self, coordinator, outcome: str) -> None:
        return None

    def on_action_complete(self, coordinator, block, nick: str, status: str) -> None:
        return None


__all__ = [
    "USER_SCOPED_BLOCKS",
    "STANDALONE_NICK",
    "RETIRED_BLOCK_KEYS",
    "normalize_blocks",
    "norm_level",
    "RunTracer",
    "RunHooks",
    "maybe_await",
    "RunHooksMixin",
]
