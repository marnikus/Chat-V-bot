"""EventBus — synchronous pub/sub for in-process decoupling."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Any


class EventBus:
    """Simple synchronous event bus.

    Handlers are functions(payload). Emit never raises: a failing handler
    is caught and ignored so one bad listener cannot kill the bus.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)

    def off(self, event: str, handler: Callable[[Any], None] | None = None) -> None:
        if handler is None:
            self._handlers.pop(event, None)
        else:
            lst = self._handlers.get(event, [])
            if handler in lst:
                lst.remove(handler)
            if not lst:
                self._handlers.pop(event, None)

    def emit(self, event: str, payload: Any = None) -> None:
        for handler in list(self._handlers.get(event, [])):
            try:
                handler(payload)
            except Exception:  # noqa: BLE001
                continue

    def clear(self) -> None:
        self._handlers.clear()

    def count(self, event: str) -> int:
        return len(self._handlers.get(event, []))
