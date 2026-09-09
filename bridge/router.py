"""Router — QWebChannel entry, composes 9 domain bridges.

Keeps the external `bridge` object stable for JS while each domain owns its
Signals/Slots. For backward compatibility, `backend.bridge.Bridge` re-exports
this Router as `Bridge` (tests import from backend.bridge).
"""

from __future__ import annotations

import logging
try:
    from PySide6.QtCore import QObject, Signal, Slot
except Exception:  # noqa: BLE001
    QObject = object  # type: ignore
    Signal = Slot = lambda *a, **kw: (lambda f: f)  # type: ignore
try:
    from qasync import asyncSlot  # noqa: F401
except Exception:  # noqa: BLE001
    asyncSlot = lambda *a, **kw: (lambda f: f)  # type: ignore

from core.result import Result

log = logging.getLogger("chatbot")


class Router(QObject):
    """Aggregates domain bridges; registered as `bridge` in QWebChannel."""

    # aggregated signals (re-emitted from domains for JS compatibility)
    users_updated = Signal(str)
    step_complete = Signal(str, str)
    step_started = Signal(int, str, str)
    stack_complete = Signal()
    log_message = Signal(str, str)
    connection_status = Signal(str)
    stats_updated = Signal(str)
    tabs_received = Signal(str)
    preset_list_updated = Signal(str)
    template_list_updated = Signal(str)
    url_presets_updated = Signal(str)
    custom_blocks_updated = Signal(str)
    tab_match_result = Signal(str, str)
    users_deleted = Signal(str, int)
    person_found = Signal(str)
    person_removed = Signal(str)
    stack_loaded = Signal(str, str)
    grid_layout_changed = Signal(str)
    grid_layout_persisted = Signal(bool)
    template_loaded = Signal(str, str)
    history_changed = Signal()
    history_page_ready = Signal(str, str)
    history_search_ready = Signal(str, str)
    history_stats_ready = Signal(str, str)
    userdb_page_ready = Signal(str, str)
    userdb_changed = Signal(str)
    media_ready = Signal(str, str)
    collector_status = Signal(str)
    collector_log = Signal(str)
    history_appended = Signal(str)
    my_nick_changed = Signal(str)
    history_error = Signal(str, str)
    labels_changed = Signal(str)
    db_info_ready = Signal(str, str)
    db_changed = Signal(str)

    def __init__(self, cdp=None, memory=None, criteria=None, engine=None, config=None, parent=None):
        super().__init__(parent)
        self._cdp = cdp
        self._memory = memory
        self._criteria = criteria
        self._engine = engine
        self._config = config
        self._domains = {}
        self._attach_domains()

    def _attach_domains(self):
        """Instantiate domain bridges and wire their signals to router's."""
        # Lazy imports to avoid cycles; domains are thin QObject wrappers
        try:
            from .cdp_bridge import CdpBridge
            from .stack_bridge import StackBridge
            from .people_bridge import PeopleBridge
            from .history_bridge import HistoryBridge
            from .label_bridge import LabelBridge
            from .db_bridge import DbBridge
            from .collector_bridge import CollectorBridge
            from .undo_bridge import UndoBridge
            from .layout_bridge import LayoutBridge

            ctx = dict(cdp=self._cdp, memory=self._memory, criteria=self._criteria, engine=self._engine, config=self._config, router=self)
            for name, Cls in [
                ("cdp", CdpBridge), ("stack", StackBridge), ("people", PeopleBridge),
                ("history", HistoryBridge), ("label", LabelBridge), ("db", DbBridge),
                ("collector", CollectorBridge), ("undo", UndoBridge), ("layout", LayoutBridge),
            ]:
                try:
                    inst = Cls(ctx, parent=self)
                    self._domains[name] = inst
                    # expose as attribute for JS: bridge.cdp / bridge.stack etc. are optional
                    setattr(self, name, inst)
                    # fan-out signals (if domain emits, router re-emits)
                    for sig_name in ["users_updated", "log_message", "connection_status", "history_error"]:
                        if hasattr(inst, sig_name) and hasattr(self, sig_name):
                            try:
                                getattr(inst, sig_name).connect(getattr(self, sig_name).emit)
                            except Exception:
                                pass
                except Exception as exc:  # noqa: BLE001
                    log.warning("domain %s init failed: %s", name, exc)
        except Exception as exc:  # noqa: BLE001
            log.debug("router domain attach skipped: %s", exc)

    # Compatibility: expose legacy Bridge API by delegating to domains or to a
    # fallback legacy Bridge instance (when domains not yet fully migrated).
    def attach_history(self, service):
        # Delegate to history & collector domains if present
        for d in self._domains.values():
            if hasattr(d, "attach_history"):
                try:
                    d.attach_history(service)
                except Exception:
                    pass
        # also keep legacy behaviour if we wrap a legacy Bridge
        legacy = getattr(self, "_legacy", None)
        if legacy:
            try:
                legacy.attach_history(service)
            except Exception:
                pass

    # Expose a Result helper for domain bridges
    def result_ok(self, value=None) -> Result:
        return Result.ok(value)

    def result_err(self, msg: str) -> Result:
        return Result.err(msg)
