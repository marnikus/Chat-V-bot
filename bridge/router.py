"""Router — the ONE QObject registered on the QWebChannel.

Publishes every domain bridge's @Slot methods and re-emits every domain
signal under the historical names, so the JS wire API is 100% unchanged
while the implementation is split by domain. Holds no domain state: the
shared BridgeContext carries the dependencies, and each domain bridge
owns its slots.

The class is assembled dynamically with Shiboken.ObjectType (PySide6's
QObject metaclass) from the nine domain bridges' metaobjects — verified
to publish slots and signals exactly like a hand-written class. A build-
time parity check guarantees nothing is silently missing.

Legacy compatibility (the test suite is the contract):
  * constructor keeps the historical kwargs;
  * private attribute names (`_config`, `_memory`, …) are write-through
    properties onto the context, so `Bridge.__new__` + manual attribute
    injection still works;
  * grid-spec classmethods/constants and undo constants are re-exported.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Type

from PySide6.QtCore import QMetaMethod, QObject, Signal, Slot

from bridge.collector_bridge import CollectorBridge
from bridge.context import BridgeContext
from bridge.cdp_bridge import CdpBridge
from bridge.db_bridge import DbBridge
from bridge.history_bridge import HistoryBridge
from bridge.label_bridge import LabelBridge
from bridge.layout_bridge import LayoutBridge
from bridge.people_bridge import PeopleBridge
from bridge.stack_bridge import StackBridge
from bridge.undo_bridge import UndoBridge
from core.events import LogMessage
from services.people_service import people_row
from services.run_service import normalize_blocks
from services.undo_service import UndoService
from stores.preset_store import PresetStore

log = logging.getLogger("chatbot")

#: the nine domain bridges, in wiring order
BRIDGE_CLASSES = [CdpBridge, StackBridge, PeopleBridge, HistoryBridge,
                  LabelBridge, DbBridge, CollectorBridge, UndoBridge,
                  LayoutBridge]

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


def _build_router_class() -> Type[QObject]:
    Meta = type(QObject)          # Shiboken.ObjectType
    ns: dict = {}

    # 1 — signals: one same-named Signal per bridge signal + log_message
    seen_signals: dict[str, list] = {}
    for cls in BRIDGE_CLASSES:
        signals, _slots = _meta_members(cls)
        BRIDGE_SPECS[cls.__name__] = (signals, _slots)
        for name, types in signals:
            if name in seen_signals:
                raise ValueError(f"signal {name!r} is defined by both "
                                 f"{seen_signals[name]} and {cls.__name__}")
            seen_signals[name] = cls.__name__
            ns[name] = Signal(*types)
    ns["log_message"] = Signal(str, str)      # router-owned (LogMessage)

    # 2 — forwarding slots with identical signatures
    seen_slots: dict[str, list] = {}
    for cls in BRIDGE_CLASSES:
        _signals, slots = _meta_members(cls)
        for name, types, ret in slots:
            if name in seen_slots:
                raise ValueError(f"slot {name!r} is defined by both "
                                 f"{seen_slots[name]} and {cls.__name__}")
            seen_slots[name] = cls.__name__
            deco = Slot(*types, result=ret) if ret else Slot(*types)
            ns[name] = deco(_make_forwarder(cls, name))

    # 3 — class attributes re-exported for legacy callers (tests)
    for attr in ("GRID_VERSION", "WINDOW_IDS", "V1_WINDOW_IDS",
                 "V2_WINDOW_IDS", "V3_WINDOW_IDS", "LEGACY_WINDOW_IDS",
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

    # 4 — the hand-written Router surface
    ns.update(_ROUTER_METHODS)
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


@_router_method
def __init__(self, cdp=None, memory=None, criteria=None, engine=None,
             config=None, presets=None, parent=None, **_legacy):
    QObject.__init__(self, parent)
    if presets is None and config is not None:
        presets = PresetStore(config=config)
    self._ctx = BridgeContext(cdp=cdp, memory=memory, criteria=criteria,
                              engine=engine, config=config,
                              presets=presets)
    self._bridges: dict = {}
    # one-time legacy preset import (SQLite era), as the old bridge did
    if presets is not None:
        try:
            presets.import_legacy()
        except Exception as exc:                        # noqa: BLE001
            log.debug("legacy preset import skipped: %s", exc)
    # build every domain bridge eagerly (normal path): signals get wired,
    # the engine/collector connections install
    for cls in BRIDGE_CLASSES:
        self._bridge(cls)
    # the run queue's label guard
    self._bridge(LabelBridge).install_label_guard()
    # forward the CDP client's connection signals as bus events
    if cdp is not None:
        self._ctx.cdp_service
    # one log signal for every domain
    self._ctx.bus.subscribe(LogMessage,
                            lambda e: self.log_message.emit(e.message,
                                                            e.level))


@_router_method
def _ensure_ctx(self):
    """A `Bridge.__new__`-assembled router (tests) skips __init__: its
    context and bridge table are created on first touch instead."""
    ctx = getattr(self, "_ctx", None)
    if ctx is None:
        ctx = BridgeContext()
        self._ctx = ctx
    bridges = getattr(self, "_bridges", None)
    if bridges is None:
        bridges = {}
        self._bridges = bridges
    return ctx, bridges


@_router_method
def _bridge(self, bridge_cls):
    """Lazily (or eagerly, from __init__) build one domain bridge and
    wire its signals to the router's same-named signals."""
    _ctx, bridges = self._ensure_ctx()
    key = bridge_cls.__name__
    bridge = bridges.get(key)
    if bridge is None:
        bridge = bridge_cls(_ctx, parent=self)
        specs, _slots = BRIDGE_SPECS.get(
            bridge_cls.__name__,
            _meta_members(bridge_cls))
        for name, _types in specs:
            router_signal = getattr(self, name, None)
            bridge_signal = getattr(bridge, name, None)
            if router_signal is not None and bridge_signal is not None:
                bridge_signal.connect(router_signal)
        bridges[key] = bridge
    return bridge


# ── legacy write-through attribute surface ─────────────────────────
def _ctx_property(field, setter_sync=True):
    def getter(self):
        ctx, _bridges = self._ensure_ctx()
        return getattr(ctx, field)

    def setter(self, value):
        ctx, _bridges = self._ensure_ctx()
        setattr(ctx, field, value)
        if setter_sync:
            ctx.sync_services()
    return property(getter, setter)


for _field in ("cdp", "memory", "criteria", "engine", "config", "presets",
               "labels", "dbs"):
    _ROUTER_METHODS["_" + _field] = _ctx_property(_field)
_ROUTER_METHODS["_history"] = _ctx_property("archive")
_ROUTER_METHODS["_archive"] = property(
    lambda self: getattr(self._ctx, "archive", None))


def _label_store(self):
    ctx, _bridges = self._ensure_ctx()
    return ctx.label_store()


def _db_manager(self):
    ctx, _bridges = self._ensure_ctx()
    manager = ctx.db_manager()
    if ctx.archive is not None:
        manager.attach(ctx.archive)
    return manager


_ROUTER_METHODS["label_store"] = property(_label_store)
_ROUTER_METHODS["db_manager"] = property(_db_manager)


@_router_method
def attach_history(self, service) -> None:
    """Wire the archive service (created in main.py) into the UI."""
    ctx, _bridges = self._ensure_ctx()
    ctx.attach_archive(service)
    self._bridge(DbBridge)
    if ctx.dbs is not None:
        ctx.dbs.attach(service)
    if service is None:
        return
    # Labels are per-WORLD data: the store is bound to the active
    # database and re-loaded on every world switch; mutations write
    # through to the world's tables on this bridge's loop.
    store = ctx.label_store()
    store.set_scheduler(
        lambda coro: self._bridge(HistoryBridge)._run_async("labels", coro))
    try:
        service.bind_labels(store)
    except Exception as exc:                            # noqa: BLE001
        log.warning("label store not bound: %s", exc)
    self._bridge(CollectorBridge).attach_archive(service)
    engine = ctx.engine
    if engine is not None:
        try:
            engine.history = service
        except Exception:                               # noqa: BLE001
            pass


@_router_method
async def sync_world_state(self) -> None:
    """Rebuild the unified undo timeline after a world change."""
    ctx, _bridges = self._ensure_ctx()
    await ctx.undo.sync_world_state()


# ── legacy instance methods used by tests ──────────────────────────
@_router_method
async def _refresh_users(self):
    await self._bridge(PeopleBridge)._refresh_users_async()


@_router_method
async def _do_delete_one(self, nick):
    await self._bridge(PeopleBridge)._do_delete_one(nick)


@_router_method
async def _do_delete_many(self, nicks):
    await self._bridge(PeopleBridge)._do_delete_many(nicks)


@_router_method
async def _do_set_messaged(self, nick, messaged):
    await self._bridge(PeopleBridge)._do_set_messaged(nick, messaged)


@_router_method
async def _do_reset(self):
    await self._bridge(PeopleBridge)._do_reset()


@_router_method
async def _do_clear(self):
    await self._bridge(PeopleBridge)._do_clear()


@_router_method
async def _people_rows(self):
    ctx, _b = self._ensure_ctx()
    return await ctx.people.rows()


@_router_method
def _push_people_entry(self, before, after):
    if before == after:
        return False
    ctx, _b = self._ensure_ctx()
    result = ctx.undo.push("people",
                          {"before": before, "after": after})
    return bool(result.is_ok)


@_router_method
def _labels_for_nicks(self, nicks):
    ctx, _b = self._ensure_ctx()
    return ctx.people.labels_for_nicks(nicks)


@_router_method
def _install_label_guard(self):
    self._bridge(LabelBridge).install_label_guard()


@_router_method
def _get_global_history(self):
    ctx, _b = self._ensure_ctx()
    return ctx.undo.history()


@_router_method
def _set_global_history(self, history, index):
    ctx, _b = self._ensure_ctx()
    ctx.undo.set_history(history, index)


def _undo_pendings(self):
    """Pending world-undo save tasks (compat: tests drain them)."""
    ctx, _b = self._ensure_ctx()
    return getattr(ctx.undo, "_undo_pendings", [])


_ROUTER_METHODS["_undo_pendings"] = property(_undo_pendings)


@_router_method
def _push_global(self, kind, value):
    ctx, _b = self._ensure_ctx()
    result = ctx.undo.push(kind, value)
    return result.value if result.is_ok else None


@_router_method
def _get_history(self):
    ctx, _b = self._ensure_ctx()
    return ctx.undo.stack_projection()


@_router_method
def _set_history(self, history, index, save=True):
    ctx, _b = self._ensure_ctx()
    ctx.undo.set_stack_projection(history, index)


@_router_method
def _push_history(self, blocks):
    ctx, _b = self._ensure_ctx()
    return ctx.undo.push_stack(blocks)


@_router_method
def _get_hist(self, kind):
    ctx, _b = self._ensure_ctx()
    return ctx.undo.kind_projection(kind)


@_router_method
def _set_hist(self, kind, hist, idx):
    ctx, _b = self._ensure_ctx()
    if kind == "stack":
        ctx.undo.set_stack_projection(hist, idx)
    else:
        entries = [ctx.undo._history_entry(kind, value)
                   for value in hist]
        ctx.undo.set_history(entries,
                             max(-1, min(idx, len(entries) - 1)))


@_router_method
def _push_hist(self, kind, value):
    ctx, _b = self._ensure_ctx()
    if kind == "stack":
        value = normalize_blocks(value)
    ctx.undo.push(kind, value)
    return ctx.undo.kind_projection(kind)


Router = _build_router_class()
