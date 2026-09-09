"""Bridge shim — delegates to bridge.Router ( <150, replaces 2486 god )."""
from bridge import Router as Bridge  # noqa: F401
from bridge.router import Router  # noqa: F401

__all__ = ["Bridge", "Router"]
