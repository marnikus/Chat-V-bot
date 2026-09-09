"""Container — a ~40-line dependency-injection container.

No third-party library. `main.py` is the ONLY place that calls
``register``; everything else resolves dependencies at construction from
the container or receives them as arguments.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

log = logging.getLogger("chatbot")


class Container:
    """Factories are called lazily, once; the instance is cached."""

    def __init__(self) -> None:
        self._factories: Dict[str, Callable[["Container"], Any]] = {}
        self._instances: Dict[str, Any] = {}

    def register(self, name: str,
                 factory: Callable[["Container"], Any],
                 *, replace: bool = False) -> None:
        if name in self._factories and not replace:
            raise ValueError(f"container already has {name!r}")
        self._factories[name] = factory
        self._instances.pop(name, None)

    def register_value(self, name: str, value: Any) -> None:
        """Register an already-built instance (wiring done by hand)."""
        self._factories.pop(name, None)
        self._instances[name] = value

    def has(self, name: str) -> bool:
        return name in self._factories or name in self._instances

    def get(self, name: str) -> Any:
        if name in self._instances:
            return self._instances[name]
        try:
            factory = self._factories[name]
        except KeyError:
            raise KeyError(
                f"nothing registered as {name!r} — main.py wires the "
                "container; check the registration order") from None
        building: List[str] = getattr(self, "_building", [])
        if name in building:
            chain = " -> ".join(building + [name])
            raise ValueError(f"dependency cycle: {chain}")
        building.append(name)
        self._building = building
        try:
            instance = factory(self)
        finally:
            building.pop()
            self._building = building
        self._instances[name] = instance
        return instance

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    def clear(self) -> None:
        self._factories.clear()
        self._instances.clear()
