"""Compatibility shim — the collector lives in services/collector_service.py."""

from backend.legacy_shims import deprecated_module

deprecated_module("collector", "services.collector_service")

from services.collector_service import (  # noqa: F401
    Collector, CollectorState, DEFAULTS,
)
from services.collector_states import CollectorDeps  # noqa: F401

__all__ = ["Collector", "CollectorDeps", "CollectorState", "DEFAULTS"]
