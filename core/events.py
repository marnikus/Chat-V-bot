"""EventBus — a lightweight typed event bus, pure Python (no Qt).

Services emit domain events; bridges subscribe and forward them to JS via
pyqtSignal. This is what decouples services from bridges: a service knows
that "the people list changed", not that a QWebChannel object exists.

Dispatch is synchronous, in subscription order, on the caller's thread.
An exception in one handler is logged and never breaks the others or the
emitter (a UI refresh bug must not corrupt a database write).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Type, TypeVar

log = logging.getLogger("chatbot")

E = TypeVar("E", bound="Event")


class Event:
    """Base class for every domain event (a plain dataclass carrier)."""


# ── people domain ────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class PeopleChanged(Event):
    """The people list was mutated (delete/mark/clear/restore). Reload it."""

    reason: str = ""                    # e.g. "marked", "deleted", "restored"
    nicks: tuple = ()


@dataclass(frozen=True, slots=True)
class UsersDeleted(Event):
    """A deletion finished — the selection UI drops the rows."""

    nicks_json: str = "[]"
    count: int = 0


@dataclass(frozen=True, slots=True)
class LogMessage(Event):
    """One line for the Log Console (message, level)."""

    message: str = ""
    level: str = "info"


# ── layout domain ────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class GridLayoutChanged(Event):
    """The active grid layout was replaced (undo/redo walked onto it)."""

    payload: str = ""


@dataclass(frozen=True, slots=True)
class PersonFound(Event):
    """A person just passed the filter during Scroll & Parse."""

    payload: str                        # JSON — the wire payload


@dataclass(frozen=True, slots=True)
class PersonRemoved(Event):
    """A person failed the filter and was purged from the list."""

    payload: str                        # JSON — the wire payload


@dataclass(frozen=True, slots=True)
class PersonMarked(Event):
    """A run just messaged `nick` — flip the row live."""

    nick: str = ""


# ── connection / tabs domain ─────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class TabsReceived(Event):
    payload: str                        # JSON: [{id, title, url, ws_url}]


@dataclass(frozen=True, slots=True)
class ConnectionChanged(Event):
    status: str                         # connected | disconnected | error


@dataclass(frozen=True, slots=True)
class TabMatchResult(Event):
    """URL-preset query resolved against the open tabs."""

    query: str
    matches_json: str                   # JSON list of matches


# ── stack / presets domain ───────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class StackLoaded(Event):
    name: str
    payload: str                        # JSON blocks


@dataclass(frozen=True, slots=True)
class PresetsChanged(Event):
    kind: str                           # stacks | templates | custom_blocks | urls
    payload: str = ""                   # JSON list


# ── undo domain ──────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class UndoHistoryChanged(Event):
    """The global timeline grew or its pointer moved."""


# ── labels domain ────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class LabelsChanged(Event):
    payload: str                        # JSON: the whole labels state


# ── database domain ──────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class DbChanged(Event):
    """A world was created/loaded/deleted/cleaned (or an undo of one)."""

    action: str                         # create | load | delete | clean | undo | redo
    payload: str = ""                   # JSON: the db_changed wire payload


@dataclass(frozen=True, slots=True)
class UserDbChanged(Event):
    """Archive contents changed — caches of the User Database window drop."""

    payload: str                        # JSON {action, nick, ...}


# ── collector / archive domain ───────────────────────────────────────
@dataclass(frozen=True, slots=True)
class MyNickChanged(Event):
    nick: str = ""


@dataclass(frozen=True, slots=True)
class ArchiveUndoApplied(Event):
    """An undo/redo re-applied an archive command."""

    forward: bool
    op: str = ""
    nick: str = ""
    ok: bool = True                     # False = the state could not be re-applied


class EventBus:
    """Subscribe/emit with typed events. Handlers take one argument: the
    event instance. `subscribe` returns an unsubscribe callable."""

    def __init__(self) -> None:
        self._subs: Dict[Type[Event], List[Callable[[Any], None]]] = {}

    def subscribe(self, event_type: Type[E],
                  handler: Callable[[E], None]) -> Callable[[], None]:
        handlers = self._subs.setdefault(event_type, [])
        if handler not in handlers:
            handlers.append(handler)
        return lambda: self.unsubscribe(event_type, handler)

    def unsubscribe(self, event_type: Type[E],
                    handler: Callable[[E], None]) -> None:
        handlers = self._subs.get(event_type)
        if handlers and handler in handlers:
            handlers.remove(handler)

    def emit(self, event: E) -> None:
        for handler in list(self._subs.get(type(event), ())):
            try:
                handler(event)
            except Exception as exc:              # noqa: BLE001
                log.warning("event handler %r failed on %s: %s",
                            handler, type(event).__name__, exc)

    def handlers_of(self, event_type: Type[Event]) -> List[Callable]:
        return list(self._subs.get(event_type, ()))
