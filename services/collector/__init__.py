"""The passive private-chat collector, split by single responsibility.

`Collector` is the facade over five mixins (lifecycle / heartbeat / push /
archive / status); `services/collector_service` re-exports the frozen seam.
See `docs/archive/2026-09-12-god-classes/STEP4_COLLECTOR_DESIGN_2026-09-12.md`.
"""

from .collector import Collector
from .constants import CollectorState, DEFAULTS

__all__ = [
    "Collector",
    "CollectorState",
    "DEFAULTS",
]
