"""Typing.Protocol interfaces — bridges depend on these, not concretes."""

from __future__ import annotations

from typing import Protocol, Any, Callable, runtime_checkable

from core.result import Result


@runtime_checkable
class Store(Protocol):
    def load(self) -> dict[str, Any]:  # noqa: D102
        ...

    def save(self, data: dict[str, Any]) -> Result[None]:  # noqa: D102
        ...


@runtime_checkable
class SettingsStoreProto(Protocol):
    def get(self, *keys: str, default: Any = None) -> Any:  # noqa: D102
        ...

    def set(self, *keys_and_value: Any) -> None:  # noqa: D102
        ...

    def save(self) -> Result[None]:  # noqa: D102
        ...


@runtime_checkable
class BookmarkStoreProto(Protocol):
    def all(self) -> list[str]: ...  # noqa: D102
    def add(self, url: str) -> Result[None]: ...  # noqa: D102
    def remove(self, url: str) -> Result[None]: ...  # noqa: D102


@runtime_checkable
class HistoryServiceProto(Protocol):
    async def page(self, nick: str, **kwargs: Any) -> Result[dict[str, Any]]: ...  # noqa: D102
    async def search(self, query: str, **kwargs: Any) -> Result[dict[str, Any]]: ...  # noqa: D102


@runtime_checkable
class CollectorServiceProto(Protocol):
    async def tick(self) -> Result[dict[str, Any]]: ...  # noqa: D102
    def state(self) -> dict[str, Any]: ...  # noqa: D102


@runtime_checkable
class UndoStoreProto(Protocol):
    def push(self, kind: str, value: Any) -> Result[None]: ...  # noqa: D102
    def history(self) -> tuple[list[Any], int]: ...  # noqa: D102


EventHandler = Callable[[Any], None]
