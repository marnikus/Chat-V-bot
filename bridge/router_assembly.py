"""Router assembly — the dynamic QObject class, synthesised from the bridges.

Part of the `router` family (entry point: `bridge/router.py`, Round J step
J-5). `bridge/router.py` has no `class` statement at all: `Router` is built
here by Shiboken's metaclass from the domain bridges' metaobjects, which is
the only way to publish twelve `@Slot` sets under one QWebChannel object
without a 1500-line hand-written class.

Three things live here, in this order:

* the bridge roster (`BRIDGE_CLASSES`) and the spec table the build fills in
  (`BRIDGE_SPECS`) — the two names `bridge/router.py` re-exports, because the
  suite reads them from there;
* introspection + forwarding (`_meta_members`, `_make_forwarder`, `_QT_TYPES`)
  — one forwarding slot per bridge slot, same signature;
* the four registration phases `build_router_class()` runs: signals, slots,
  legacy class attributes, then the hand-written surface collected in
  `_ROUTER_METHODS` by the `@_router_method` decorator.

The decorator is the seam that keeps the hand-written half of `Router`
readable: `bridge/router.py` and `bridge/router_legacy.py` both define methods
in module scope, decorate them, and the build picks them up — which is why the
compat surface could move to another module without renaming a single method.
"""

from __future__ import annotations

import logging
from typing import Any, Type

from PySide6.QtCore import QMetaMethod, QObject, Signal, Slot

from bridge.bot_bridge import BotBridge
from bridge.bot_prompt_bridge import BotPromptBridge
from bridge.bot_settings_bridge import BotSettingsBridge
from bridge.collector_bridge import CollectorBridge
from bridge.context import BridgeContext          # noqa: F401  (re-exported)
from bridge.cdp_bridge import CdpBridge
from bridge.db_bridge import DbBridge
from bridge.file_bridge import FileBridge
from bridge.history_bridge import HistoryBridge
from bridge.label_bridge import LabelBridge
from bridge.layout_bridge import LayoutBridge
from bridge.people_bridge import PeopleBridge
from bridge.stack_bridge import StackBridge
from bridge.undo_bridge import UndoBridge
from services.people_service import people_row
from services.run import normalize_blocks
from services.undo_service import UndoService

log = logging.getLogger("chatbot")


#: the eleven domain bridges, in wiring order
BRIDGE_CLASSES = [CdpBridge, StackBridge, FileBridge, PeopleBridge,
                  HistoryBridge, LabelBridge, DbBridge, CollectorBridge,
                  UndoBridge, LayoutBridge, BotBridge, BotPromptBridge,
                  BotSettingsBridge]


# Qt type-name → Python type for signature rebuilding
_QT_TYPES = {
    "QString": str, "QByteArray": str, "char*": str,
    "int": int, "uint": int, "long": int, "ulong": int, "qlonglong": int,
    "bool": bool, "double": float, "float": float,
    "QVariant": "QVariant",
}


def _py_type(qt_name: str) -> Any:
    return _QT_TYPES.get(qt_name, qt_name)


def _qt_text(value) -> str:
    """QByteArray (and bytes) → plain str."""
    try:
        return bytes(value).decode()
    except (TypeError, UnicodeDecodeError):
        return str(value)


def _meta_members(cls: Type[QObject]):
    """(signal specs, slot specs) of ONE bridge class, from a throwaway
    instance's metaobject. Signals: (name, [types]). Slots: (name, [types],
    return_type or None)."""
    probe = cls(BridgeContext())
    mo = probe.metaObject()
    signals, slots = [], []
    for i in range(mo.methodOffset(), mo.methodCount()):
        method = mo.method(i)
        name = _qt_text(method.name())
        params = [_qt_text(p) for p in method.parameterTypes()]
        sig_types = [_py_type(p) for p in params]
        mtype = method.methodType()
        if mtype == QMetaMethod.MethodType.Signal:
            signals.append((name, sig_types))
        elif mtype == QMetaMethod.MethodType.Slot:
            slots.append((name, sig_types, _qt_text(method.typeName())
                          or None))
    probe.deleteLater()
    return signals, slots


def _make_forwarder(bridge_cls: Type[QObject], method_name: str):
    def forward(self, *args):
        return getattr(self._bridge(bridge_cls), method_name)(*args)
    forward.__name__ = method_name
    forward.__doc__ = f"Forward to {bridge_cls.__name__}.{method_name}"
    return forward


#: static signal/slot specs per bridge class, captured from a clean
#: probe BEFORE any signal is connected. (Connecting a signal to a plain
#: bound method makes PySide6 append that method to the INSTANCE's
#: metaobject, which shifts methodOffset() — so runtime enumeration of a
#: wired bridge is unreliable. The specs below are the truth.)
BRIDGE_SPECS: dict[str, tuple] = {}



def _register_signals(ns: dict, bridge_classes: list, specs: dict) -> None:
    """1 — signals: one same-named Signal per bridge signal + log_message."""
    seen_signals: dict[str, list] = {}
    for cls in bridge_classes:
        signals, _slots = _meta_members(cls)
        specs[cls.__name__] = (signals, _slots)
        for name, types in signals:
            if name in seen_signals:
                raise ValueError(f"signal {name!r} is defined by both "
                                 f"{seen_signals[name]} and {cls.__name__}")
            seen_signals[name] = cls.__name__
            ns[name] = Signal(*types)
    ns["log_message"] = Signal(str, str)      # router-owned (LogMessage)


def _register_slots(ns: dict, bridge_classes: list) -> None:
    """2 — forwarding slots with identical signatures."""
    seen_slots: dict[str, list] = {}
    for cls in bridge_classes:
        _signals, slots = _meta_members(cls)
        for name, types, ret in slots:
            if name in seen_slots:
                raise ValueError(f"slot {name!r} is defined by both "
                                 f"{seen_slots[name]} and {cls.__name__}")
            seen_slots[name] = cls.__name__
            deco = Slot(*types, result=ret) if ret else Slot(*types)
            ns[name] = deco(_make_forwarder(cls, name))


def _register_legacy_attrs(ns: dict) -> None:
    """3 — class attributes re-exported for legacy callers (tests)."""
    for attr in ("GRID_VERSION", "WINDOW_IDS", "V1_WINDOW_IDS",
                 "V2_WINDOW_IDS", "V3_WINDOW_IDS", "V4_WINDOW_IDS",
                 "LEGACY_WINDOW_IDS",
                 "NEW_WINDOW_IDS", "MIN_GRID_SIZE", "_default_grid_tree",
                 "_leaf_ids", "_parse_grid_payload", "_validate_grid_tree",
                 "_normalize_grid_tree", "_node_type", "_migrate_grid_tree",
                 "_canonical_grid_payload", "_legacy_grid_payload"):
        ns[attr] = getattr(LayoutBridge, attr)
    for attr in ("COMMAND_KINDS", "UNDO_LABELS", "HISTORY_KINDS",
                 "WORLD_UNDO_KINDS"):
        ns[attr] = getattr(UndoService, attr)
    from services.undo_service import _values_equal
    ns["_values_equal"] = staticmethod(_values_equal)
    ns["_stacks_equal"] = staticmethod(_values_equal)
    ns["_clean_blocks"] = staticmethod(normalize_blocks)
    ns["_clean_history"] = staticmethod(UndoService._clean_history)
    ns["_history_entry"] = staticmethod(UndoService._history_entry)
    ns["_people_row"] = staticmethod(people_row)


def build_router_class(bridge_classes: list, specs: dict,
                       methods: dict) -> Type[QObject]:
    """Assemble the Router class from the four registration phases (§19.5:
    a long-and-flat synthesis — one phase, one concept, one function).

    The roster, the spec table and the hand-written method table arrive as
    arguments rather than being read from this module's globals: the entry
    module passes its own, which is what lets a test rebuild a Router from a
    patched roster.
    """
    Meta = type(QObject)          # Shiboken.ObjectType
    ns: dict = {}
    _register_signals(ns, bridge_classes, specs)
    _register_slots(ns, bridge_classes)
    _register_legacy_attrs(ns)
    # 4 — the hand-written Router surface
    ns.update(methods)
    return Meta("Router", (QObject,), ns)


# hand-written methods (defined here, injected into the class namespace)
_ROUTER_METHODS: dict = {}



def _router_method(fn_or_name=None, **kwargs):
    """Register a hand-written Router method. Usable bare (on functions)
    or with an explicit name= (on properties)."""
    if isinstance(fn_or_name, str):
        def deco(obj):
            _ROUTER_METHODS[fn_or_name] = obj
            return obj
        return deco
    _ROUTER_METHODS[getattr(fn_or_name, "__name__",
                            kwargs.get("name", "anon"))] = fn_or_name
    return fn_or_name
