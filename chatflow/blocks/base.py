"""Action-block executor contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class BlockResult:
    ok: bool = True
    data: dict = field(default_factory=dict)
    error: str = ""

    # convenience flags used by the executor
    @property
    def terminate(self) -> bool:
        return bool(self.data.get("terminate"))

    @property
    def skip_next(self) -> bool:
        return bool(self.data.get("skip_next"))


class BaseExecutor(ABC):
    """One action block type. `params_schema` drives the GUI forms."""

    action_type: str = ""
    label: str = ""
    icon: str = ""
    params_schema: list[dict] = []

    @abstractmethod
    async def execute(self, ctx, block) -> BlockResult:  # noqa: ANN001
        """Run the block. Raise StopRequested/OpError or return BlockResult."""
