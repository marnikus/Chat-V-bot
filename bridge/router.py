"""Router — the ONE QObject registered on the QWebChannel.

Publishes every domain bridge's @Slot methods and re-emits every domain
signal under the historical names, so the JS wire API is 100% unchanged
while the implementation is split by domain. Holds no domain state: the
shared BridgeContext carries the dependencies, and each domain bridge
owns its slots.

The family (Round J step J-5):
  * `bridge/router_assembly.py` — the class is *assembled* there, not
    written here: twelve bridges' metaobjects are merged with Shiboken's
    metaclass, and `@_router_method` collects the hand-written half;
  * `bridge/router_legacy.py` — the compat surface (write-through
    properties, the history/undo shims the suite drives directly);
  * this file — the boot path plus the live wire surface `attach_history`,
    `sync_world_state` and `announce_world_ready`.

Construction takes a `BridgeContext` (the G4 parameter object) or, for
callers that predate it, the historical boot keywords — `Router(cdp=…,
memory=…, criteria=…, engine=…, config=…, presets=…)` — which are turned
into a context here. The class keeps answering to its old private
attribute names, because `Bridge.__new__` + manual injection is still the
test suite's way in.
"""

from __future__ import annotations

import logging
from typing import Type

from PySide6.QtCore import QObject

from bridge import router_legacy                            # noqa: F401  (registers the compat surface)
from bridge import router_assembly
from bridge.collector_bridge import CollectorBridge
from bridge.context import BridgeContext
from bridge.db_bridge import DbBridge
from bridge.history_bridge import HistoryBridge
from bridge.label_bridge import LabelBridge
from bridge.router_assembly import (                        # noqa: F401
    BRIDGE_CLASSES, BRIDGE_SPECS, _ROUTER_METHODS, _meta_members,
    _router_method,
)
from core.events import LogMessage
from services.world_events import announce_world_live
from stores.preset_store import PresetStore

log = logging.getLogger("chatbot")

#: the historical boot keywords the context is built from, in `BridgeContext`
#: order — anything else a caller passes is tolerated and ignored, which is
#: what `**_legacy` always did.
_BOOT_KEYS = ("cdp", "memory", "criteria", "engine")


def _context_from_legacy(legacy: dict) -> BridgeContext:
    """Turn the pre-Router boot kwargs into the context they became.

    Two of them are not just moved: `presets` is *derived* from `config` when
    the caller did not pass one, exactly as the old constructor did, and the
    leftovers are reported at debug level rather than swallowed in silence.
    """
    presets = legacy.pop("presets", None)
    config = legacy.pop("config", None)
    if presets is None and config is not None:
        presets = PresetStore(config=config)
    boot = {key: legacy.pop(key, None) for key in _BOOT_KEYS}
    if legacy:
        log.debug("Router: unknown boot kwargs ignored: %s", sorted(legacy))
    return BridgeContext(config=config, presets=presets, **boot)


@_router_method
def __init__(self, ctx=None, parent=None, **legacy):
    """Build the wire object around a context (or the legacy boot kwargs)."""
    QObject.__init__(self, parent)
    self._ctx = ctx if ctx is not None else _context_from_legacy(legacy)
    self._bridges: dict = {}
    # one-time legacy preset import (SQLite era), as the old bridge did
    presets = self._ctx.presets
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
    if self._ctx.cdp is not None:
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


@_router_method
async def announce_world_ready(self) -> None:
    """The world finished opening — every window may load it now.

    Called once by `ApplicationLifecycle.startup`: the page is up long
    before `memory.init()` / `history.init()` are done, so its first list
    requests hit a closed world and the user had to press the refresh
    buttons. The broadcast reloads the People list, the Full User
    Database, the DB Connection window and the label pills instead.
    """
    ctx, _bridges = self._ensure_ctx()
    announce_world_live(ctx.bus, ctx.label_store(), reason="startup")




def _build_router_class() -> Type[QObject]:
    """Assemble `Router` from the *current* roster and method table.

    The roster and the spec table are read here, at call time, on purpose:
    the router contract tests monkeypatch `bridge.router.BRIDGE_CLASSES` /
    `BRIDGE_SPECS` and rebuild the class to prove the build rejects a
    duplicate signal or slot name. Keeping this one call site in the entry
    module is what keeps that seam alive across the split.
    """
    return router_assembly.build_router_class(BRIDGE_CLASSES, BRIDGE_SPECS,
                                              _ROUTER_METHODS)


#: the class is built last: importing `bridge.router_legacy` above already
#: registered the compat surface, so everything is in the method table.
Router = _build_router_class()
