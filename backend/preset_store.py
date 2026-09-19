"""Compatibility shim — the preset store lives in stores/ now."""

from backend.legacy_shims import deprecated_module

deprecated_module("preset_store", "stores.preset_store")

from stores.preset_store import PresetStore  # noqa: F401

__all__ = ["PresetStore"]
