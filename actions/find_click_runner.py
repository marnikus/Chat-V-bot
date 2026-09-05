"""Backwards-compatible shim.

The two-phase visual-confirmation runner now lives in
:mod:`backend.visual_click` so that *every* find-and-click block can share it
(see docs/AGENT_RULES.md). This module re-exports it so existing imports keep
working.
"""

from backend.visual_click import (  # noqa: F401
    CLICK_PAUSE_MS,
    find_and_click,
    find_and_click_exact,
)

__all__ = ["find_and_click", "find_and_click_exact", "CLICK_PAUSE_MS"]
