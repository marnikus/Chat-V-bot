"""Compatibility shim — the collector lives in services/collector_service.py."""

from services.collector_service import (  # noqa: F401
    Collector, CollectorState, DEFAULTS,
)

__all__ = ["Collector", "CollectorState", "DEFAULTS"]
