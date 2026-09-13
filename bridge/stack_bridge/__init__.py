"""The action-stack UI surface, split by single responsibility.

`StackBridge` is the facade over seven mixins (wiring / run_control /
composer / criteria / presets / templates / blocks). See
`docs/archive/2026-09-13-god-classes/STEP6_BRIDGE_FACADES_DESIGN_2026-09-13.md`.

This `__init__` re-exports the frozen seam `bridge/router.py` and the
bridge_safety tests import, so promoting the module to a package changed
no import line anywhere.
"""

from .bridge import StackBridge

__all__ = ["StackBridge"]


