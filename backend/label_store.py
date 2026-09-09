"""Compatibility shim — the label store lives in stores/ now."""

from stores.label_store import (  # noqa: F401
    LabelStore, PALETTE, DEFAULT_COLOR, MAX_NAME, normalize_color,
    FILTER_KEY,
)

__all__ = ["LabelStore", "PALETTE", "DEFAULT_COLOR", "MAX_NAME",
           "normalize_color", "FILTER_KEY"]
