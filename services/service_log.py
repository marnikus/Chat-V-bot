"""Shared log emission for the service layer (AREA C dedup).

`CdpService._log`, `PeopleService._log` and `UndoService._log` were three
identical copies of the same two-liner. Each keeps its private `_log`
method (tests call `service._log(...)`) but now delegates here, so there
is exactly one implementation.
"""

from __future__ import annotations

from core.events import LogMessage


def emit_log(bus, message: str, level: str = "info") -> None:
    """Emit one user-facing log line on the service's EventBus."""
    bus.emit(LogMessage(message=message, level=level))
