"""Shared status forwarding for Qt-free services.

The service still owns its bus. This mixin only preserves the common wire
contract; it does not normalize levels or change message text.
"""

from core.events import LogMessage


class StatusEvents:
    def _log(self, message: str, level: str = "info") -> None:
        self._bus.emit(LogMessage(message=message, level=level))
