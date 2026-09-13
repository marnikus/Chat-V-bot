"""Compatibility shim — the collector lives in `services/collector/`.

`Collector` was extracted into `services/collector/` (one mixin per
responsibility) in the god-class round, step 4. This module keeps the frozen
import seam (`from services.collector_service import Collector` used by
`services/history`, `backend.collector` and `services.collector_tick`).
"""

from services.collector import (  # noqa: F401
    Collector, CollectorState, DEFAULTS,
)
from backend.chat_parser import sync_conversation  # noqa: F401  (patch seam)

__all__ = ["Collector", "CollectorState", "DEFAULTS"]
