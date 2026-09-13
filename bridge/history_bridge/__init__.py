"""The message archive's UI surface, split by single responsibility.

`HistoryBridge` is the facade over seven mixins (runner / reads / userdb /
deletion / person_ops / media / settings); the three module-level helpers live
in `support.py`. See
`docs/archive/2026-09-13-god-classes/STEP6_BRIDGE_FACADES_DESIGN_2026-09-13.md`.

This `__init__` re-exports the frozen seam `bridge/router.py` imports
(`HistoryBridge`) plus the module-level helpers that used to sit beside the
class, so promoting the module to a package changed no import line anywhere.
"""

from .bridge import HistoryBridge
from .support import _file_mime, _person_request, _qt_clipboard

__all__ = [
    "HistoryBridge",
    "_file_mime",
    "_person_request",
    "_qt_clipboard",
]
