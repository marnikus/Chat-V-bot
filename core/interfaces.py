"""Store & repository Protocols.

Services depend on these protocols, never on the concrete stores — a unit
test can hand a service a dict-backed fake and no filesystem is touched.

The concrete implementations live in stores/ (config + SQLite I/O). The
protocols intentionally describe only what services actually call.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ── config-file stores ───────────────────────────────────────────────
@runtime_checkable
class SettingsStoreProto(Protocol):
    """The app settings tree (chrome/scroll/delays/ui/history/collector)."""

    def get(self, *keys: str, default: Any = None) -> Any: ...

    def set(self, section: str, value: Any, save: bool = True) -> None: ...

    def section(self, name: str) -> Dict[str, Any]: ...


@runtime_checkable
class PresetStoreProto(Protocol):
    """Named stack presets and message templates."""

    def save_stack(self, name: str, blocks: List[dict]) -> None: ...

    def load_stack(self, name: str) -> Optional[List[dict]]: ...

    def list_stacks(self) -> List[dict]: ...

    def delete_stack(self, name: str) -> bool: ...

    def save_template(self, name: str, body: str) -> None: ...

    def load_template(self, name: str) -> Optional[str]: ...

    def list_templates(self) -> List[dict]: ...

    def delete_template(self, name: str) -> bool: ...


@runtime_checkable
class BookmarkStoreProto(Protocol):
    """URL bookmark chips."""

    def all(self) -> List[str]: ...

    def add(self, url: str) -> bool: ...

    def remove(self, url: str) -> bool: ...


@runtime_checkable
class BlockStoreProto(Protocol):
    """Reusable custom Find & Click block definitions."""

    def all(self) -> List[dict]: ...

    def save(self, name: str, block: dict) -> bool: ...

    def delete(self, name: str) -> bool: ...


@runtime_checkable
class SessionStoreProto(Protocol):
    """Last-session state (restored on startup)."""

    def get(self, key: str, default: Any = None) -> Any: ...

    def set(self, save: bool = True, **updates: Any) -> None: ...


@runtime_checkable
class UndoStoreProto(Protocol):
    """The app-level half of the global undo timeline."""

    def load_state(self) -> tuple[list, int]: ...

    def save_state(self, history: list, index: int) -> None: ...


# ── people queue repository (async) ──────────────────────────────────
class UserRecordProto(Protocol):
    nick: str
    gender: str
    registered: bool
    anonymous: bool
    guest: bool
    first_seen: str
    last_seen: str
    messaged: bool
    message_count: int
    last_messaged: Optional[str]
    notes: str


@runtime_checkable
class PeopleRepoProto(Protocol):
    """The people queue storage the PeopleService may use."""

    db_path: str

    async def get_all(self) -> List[Any]: ...

    async def get_queue(self) -> List[Any]: ...

    async def get_stats(self) -> Dict[str, int]: ...
