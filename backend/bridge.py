"""Compatibility shim — the bridge lives in bridge/ now.

`Bridge` is the dynamically assembled Router (bridge/router.py): one
QWebChannel object publishing every domain bridge's slots and signals
under the historical names. The old monolith is preserved verbatim at
bridge/_legacy_bridge.py for reference during the transition.
"""

from bridge.router import Router as Bridge  # noqa: F401
from bridge.context import BridgeContext    # noqa: F401

__all__ = ["Bridge", "BridgeContext"]
