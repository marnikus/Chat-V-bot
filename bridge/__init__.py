"""Bridge package — router + 9 domain bridges (Step 3).

Router is the canonical QWebChannel object (was Bridge). Bridge is kept as
alias for backward compat: `from bridge import Bridge` == Router.
"""

from .router import Router  # noqa: F401

# Domain bridges are optional in headless (PySide6 missing) contexts — Router still works.
try:
    from .cdp_bridge import CdpBridge  # noqa: F401
    from .stack_bridge import StackBridge  # noqa: F401
    from .people_bridge import PeopleBridge  # noqa: F401
    from .history_bridge import HistoryBridge  # noqa: F401
    from .label_bridge import LabelBridge  # noqa: F401
    from .db_bridge import DbBridge  # noqa: F401
    from .collector_bridge import CollectorBridge  # noqa: F401
    from .undo_bridge import UndoBridge  # noqa: F401
    from .layout_bridge import LayoutBridge  # noqa: F401
except Exception:  # noqa: BLE001
    CdpBridge = StackBridge = PeopleBridge = HistoryBridge = LabelBridge = DbBridge = CollectorBridge = UndoBridge = LayoutBridge = None  # type: ignore

# Alias for backward compat; W1 target: backend/bridge.py becomes shim
Bridge = Router  # noqa: F401

__all__ = ["Router", "Bridge", "CdpBridge", "StackBridge", "PeopleBridge", "HistoryBridge", "LabelBridge", "DbBridge", "CollectorBridge", "UndoBridge", "LayoutBridge"]
