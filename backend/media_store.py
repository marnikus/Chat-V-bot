"""Compatibility shim — the media cache lives in stores/media_store.py."""

from backend.legacy_shims import deprecated_module

deprecated_module("media_store", "stores.media_store")

from stores.media_store import MediaOptions, MediaStore, slugify_nick  # noqa: F401

__all__ = ["MediaOptions", "MediaStore", "slugify_nick"]
