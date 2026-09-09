"""Core contracts: Result, EventBus, Protocols, DI container."""

from .result import Result
from .events import EventBus
from .di import Container

__all__ = ["Result", "EventBus", "Container"]
