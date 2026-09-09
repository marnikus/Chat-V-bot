"""Tiny DI container (~40 lines) — no third-party framework."""

from __future__ import annotations

from typing import Any, Callable, Dict


class Container:
    """Register factories or instances; resolve by key.

    Singleton by default; pass singleton=False for transient.
    Circular deps are not supported — keep the graph a DAG.
    """

    def __init__(self) -> None:
        self._factories: Dict[str, tuple[Callable[[Container], Any], bool]] = {}
        self._singletons: Dict[str, Any] = {}

    def register(self, key: str, factory: Callable[["Container"], Any], singleton: bool = True) -> None:
        self._factories[key] = (factory, singleton)

    def register_instance(self, key: str, instance: Any) -> None:
        self._singletons[key] = instance

    def resolve(self, key: str) -> Any:
        if key in self._singletons:
            return self._singletons[key]
        if key not in self._factories:
            raise KeyError(f"DI: no provider for '{key}'")
        factory, singleton = self._factories[key]
        instance = factory(self)
        if singleton:
            self._singletons[key] = instance
        return instance

    def has(self, key: str) -> bool:
        return key in self._singletons or key in self._factories

    def clear(self) -> None:
        self._factories.clear()
        self._singletons.clear()
