"""Inventory/deprecation stage of the Area A compatibility retirement ladder.

Exports remain intact. Removal requires separate compatibility approval;
merging unrelated workstreams alone is not authorization to delete an API.
"""
from __future__ import annotations

import warnings
from types import MappingProxyType

SHIMS = MappingProxyType({
    "action_engine": "services.run",
    "bridge": "bridge.router",
    "collector": "services.collector_service",
    "db_manager": "services.db_service",
    "history_db": "stores.history_db",
    "history_models": "stores.history_models",
    "history_repo": "stores.history_repo",
    "history_service": "services.history",
    "label_store": "stores.label_store",
    "media_store": "stores.media_store",
    "preset_store": "stores.preset_store",
    "user_memory": "stores.user_memory",
})


def deprecated_module(name: str, target: str) -> None:
    """Warn at the importer, refusing unknown or inconsistent mappings."""
    if name not in SHIMS:
        raise KeyError(name)
    if target != SHIMS[name]:
        raise ValueError(f"wrong replacement for backend.{name}")
    warnings.warn(f"backend.{name} is a compatibility shim; import {target} "
                  f"instead (Area A retirement ladder, rung 1)",
                  DeprecationWarning, stacklevel=3)
