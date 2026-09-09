"""Typing.Protocol interfaces — bridges depend on these, not concretes.

Reusability: any module can depend on a Protocol without importing the
concrete backend/history_service. Fake implementations for tests only need
to implement the Protocol methods.
"""

from __future__ import annotations

from typing import Protocol, Any, Callable, runtime_checkable, Optional

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
    def add(self, url: str) -> bool: ...  # noqa: D102
    def remove(self, url: str) -> bool: ...  # noqa: D102


@runtime_checkable
class PresetStoreProto(Protocol):
    def save_stack(self, name: str, blocks: Any) -> None: ...  # noqa: D102
    def load_stack(self, name: str) -> Any: ...  # noqa: D102
    def list_stacks(self) -> list: ...  # noqa: D102
    def delete_stack(self, name: str) -> bool: ...  # noqa: D102
    def save_template(self, name: str, body: Any) -> None: ...  # noqa: D102
    def load_template(self, name: str) -> Any: ...  # noqa: D102
    def list_templates(self) -> list: ...  # noqa: D102
    def delete_template(self, name: str) -> bool: ...  # noqa: D102


@runtime_checkable
class BlockStoreProto(Protocol):
    def all(self) -> list: ...  # noqa: D102
    def save_block(self, name: str, block: Any) -> bool: ...  # noqa: D102
    def delete(self, name: str) -> bool: ...  # noqa: D102


@runtime_checkable
class SessionStoreProto(Protocol):
    def get(self, key: str, default: Any = None) -> Any:  # noqa: D102
        ...

    def set(self, *args: Any, **kwargs: Any) -> None:  # noqa: D102
        ...


@runtime_checkable
class HistoryServiceProto(Protocol):
    """15-method trimmed surface — the only history API bridges may use.

    Each async method returns Result[T]; sync getters return Result as well.
    MediaStore is never accessed directly — go through HistoryService or
    MediaService.
    """

    async def init(self) -> Result[Any]: ...  # noqa: D102
    async def close(self) -> Result[None]: ...  # noqa: D102
    def start(self) -> Result[None]: ...  # noqa: D102
    def settings(self) -> Result[dict[str, Any]]: ...  # noqa: D102
    def apply_settings(self, patch: dict[str, Any]) -> Result[dict[str, Any]]: ...  # noqa: D102
    async def page(self, nick: str, **kwargs: Any) -> Result[dict[str, Any]]: ...  # noqa: D102
    def preview_settings(self) -> Result[dict[str, Any]]: ...  # noqa: D102
    def set_my_nick(self, nick: str) -> Result[str]: ...  # noqa: D102
    async def load_world_undo(self) -> Result[list[dict[str, Any]]]: ...  # noqa: D102
    async def save_world_undo(self, entries: list[dict[str, Any]]) -> Result[None]: ...  # noqa: D102
    async def switch_db(self, path: str) -> Result[dict[str, Any]]: ...  # noqa: D102
    async def migrate_install(self) -> Result[dict[str, Any]]: ...  # noqa: D102
    def world_media_dir(self, path: str = "") -> Result[str]: ...  # noqa: D102
    def media_base_dir(self) -> Result[str]: ...  # noqa: D102
    @property
    def query(self) -> Any: ...  # noqa: D102


@runtime_checkable
class MediaServiceProto(Protocol):
    """Media owned via HistoryService — no direct repo."""

    def media_base_dir(self) -> Result[str]: ...  # noqa: D102
    def world_media_dir(self, path: str = "") -> Result[str]: ...  # noqa: D102
    def folder_for(self, nick: str) -> Result[str]: ...  # noqa: D102
    def cache_usage(self) -> Result[dict[str, Any]]: ...  # noqa: D102


@runtime_checkable
class DbServiceProto(Protocol):
    async def switch_db(self, path: str) -> Result[dict[str, Any]]: ...  # noqa: D102
    async def load_world_undo(self) -> Result[list[dict[str, Any]]]: ...  # noqa: D102
    async def save_world_undo(self, entries: list[dict[str, Any]]) -> Result[None]: ...  # noqa: D102
    async def migrate_install(self) -> Result[dict[str, Any]]: ...  # noqa: D102


@runtime_checkable
class CollectorServiceProto(Protocol):
    async def tick(self) -> Result[dict[str, Any]]: ...  # noqa: D102
    async def backfill(self) -> Result[dict[str, Any]]: ...  # noqa: D102
    def state(self) -> Result[dict[str, Any]]: ...  # noqa: D102
    async def set_my_nick(self, nick: str) -> Result[str]: ...  # noqa: D102


@runtime_checkable
class UndoStoreProto(Protocol):
    def load_state(self) -> tuple[list[Any], int]: ...  # noqa: D102
    def save_state(self, history: list[Any], index: int) -> Any: ...  # noqa: D102


@runtime_checkable
class PeopleRepoProto(Protocol):
    """Async people reads. Methods only — data members would break
    runtime_checkable isinstance()."""

    async def get_all(self) -> list: ...  # noqa: D102
    async def get_queue(self) -> list: ...  # noqa: D102
    async def get_stats(self) -> dict: ...  # noqa: D102


class UserRecordProto(Protocol):
    """Documented user-record fields (typing only, never isinstance)."""

    nick: str
    gender: str
    registered: bool
    anonymous: bool
    guest: bool
    first_seen: str
    last_seen: str
    messaged: bool
    message_count: int
    last_messaged: Any
    notes: str


EventHandler = Callable[[Any], None]
