"""Compatibility shim — the media cache lives in stores/media_store.py."""

from stores.media_store import MediaOptions, MediaStore, slugify_nick  # noqa: F401

__all__ = ["MediaOptions", "MediaStore", "slugify_nick"]
