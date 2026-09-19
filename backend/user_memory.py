"""Compatibility shim — the people queue store lives in stores/user_memory.py."""

from backend.legacy_shims import deprecated_module

deprecated_module("user_memory", "stores.user_memory")

from stores.user_memory import UserMemory, UserRecord, _SCHEMA  # noqa: F401

__all__ = ["UserMemory", "UserRecord", "_SCHEMA"]
