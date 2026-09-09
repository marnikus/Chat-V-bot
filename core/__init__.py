"""core — zero-dependency contracts shared by every layer.

Nothing in this package imports from backend/, bridge/, services/, stores/
or actions/: the dependency arrows flow DOWN only (core is the bottom).
"""

from core.result import Result, Ok, Err
from core.events import EventBus
from core.di import Container

__all__ = ["Result", "Ok", "Err", "EventBus", "Container"]
