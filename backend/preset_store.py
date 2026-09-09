"""Compatibility shim — the preset store lives in stores/ now."""

from stores.preset_store import PresetStore  # noqa: F401

__all__ = ["PresetStore"]
