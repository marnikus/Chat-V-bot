"""Compatibility shim — the label store lives in stores/ now."""

from backend.legacy_shims import deprecated_module

deprecated_module("label_store", "stores.label_store")

from stores.label_store import (  # noqa: F401
    LabelStore, PALETTE, DEFAULT_COLOR, MAX_NAME, normalize_color,
    FILTER_KEY,
)

__all__ = ["LabelStore", "PALETTE", "DEFAULT_COLOR", "MAX_NAME",
           "normalize_color", "FILTER_KEY"]
