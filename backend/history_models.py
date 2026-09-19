"""Compatibility shim — the archive models live in stores/history_models.py."""

from backend.legacy_shims import deprecated_module

deprecated_module("history_models", "stores.history_models")

from stores.history_models import *  # noqa: F401,F403
from stores.history_models import (  # noqa: F401
    MAX_LIVE_ITEMS, Alignment, MessageRecord, fingerprint,
)
