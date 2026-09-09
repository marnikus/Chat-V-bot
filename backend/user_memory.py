"""Compatibility shim — the people queue store lives in stores/user_memory.py."""

from stores.user_memory import UserMemory, UserRecord, _SCHEMA  # noqa: F401

__all__ = ["UserMemory", "UserRecord", "_SCHEMA"]
