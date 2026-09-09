"""Services — async, return Result[T]; bridges use @asyncSlot.

Each service <150 LOC, single responsibility, reusable without Qt.
"""

from .collector_service import CollectorService  # noqa: F401
from .history_service import HistoryService  # noqa: F401
from .media_service import MediaService  # noqa: F401
from .db_service import DbService  # noqa: F401

__all__ = ["CollectorService", "HistoryService", "MediaService", "DbService"]
