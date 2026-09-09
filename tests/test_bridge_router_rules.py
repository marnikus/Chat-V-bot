"""D1 — Router wire contract (design IDs R-1..R-12).

The Router is the ONE QObject on the QWebChannel. Everything below pins
the *wire* contract the JS side depends on (see
docs/plans/BRIDGE_TESTS_DESIGN_2026-09-09.md):

  R-1  every domain signal is published as a Signal
  R-2  every domain slot is published as a Slot with its arity
  R-3  slots forward args verbatim and return the domain value
  R-4  domain signals re-emit on the Router with payload intact
  R-5  a duplicate/unknown name fails the build LOUDLY (no half router)
  R-6  domain bridges are built once (lazy path) — never rebuilt
  R-7  legacy attribute injection is write-through for late deps
  R-8  grid/undo class attributes are re-exported
  R-9  Router can be subclassed (legacy FakeBridge pattern)
  R-10 a slot call routes to exactly one domain bridge (no cycles)
  R-11 log_message re-exported and driven by the bus
  R-12 every `bridge.X(` name used by ui/js/*.js exists on the Router

Run:  python -m pytest tests/test_bridge_router_rules.py
"""

import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QMetaMethod, QObject, Signal, Slot  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from bridge.cdp_bridge import CdpBridge  # noqa: E402
from bridge.router import (BRIDGE_CLASSES, BRIDGE_SPECS,  # noqa: E402
                           _build_router_class, _make_forwarder)
from bridge.stack_bridge import StackBridge  # noqa: E402
from bridge.undo_bridge import UndoBridge  # noqa: E402
from services.undo_service import UndoService  # noqa: E402

from bridge_harness import FakeEngine, Recorder, TempWorld, make_bare  # noqa: E402

UI_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "ui", "js")


def meta_names(inst):
    mo = inst.metaObject()
    out = {}
    for i in range(mo.methodOffset(), mo.methodCount()):
        m = mo.method(i)
        out[bytes(m.name()).decode()] = m.methodType()
    return out


def bare_router():
    return Bridge.__new__(Bridge), QObject.__init__


class TestPublishedSurface(unittest.TestCase):
    """R-1 / R-2 — the published metaobject is the wire."""

    def setUp(self):
        self.inst = Bridge.__new__(Bridge)
        QObject.__init__(self.inst)
        self.published = meta_names(self.inst)

    def test_R1_every_domain_signal_is_a_signal(self):
        for cls in BRIDGE_CLASSES:
            signals, _ = BRIDGE_SPECS[cls.__name__]
            for name, _types in signals:
                self.assertIn(name, self.published, f"{cls.__name__}.{name}")
                self.assertEqual(self.published[name],
                                 QMetaMethod.MethodType.Signal,
                                 f"{name} must stay a Signal")

    def test_R2_every_domain_slot_is_a_slot_with_arity(self):
        for cls in BRIDGE_CLASSES:
            _, slots = BRIDGE_SPECS[cls.__name__]
            for name, types, _ret in slots:
                self.assertIn(name, self.published, f"{cls.__name__}.{name}")
                self.assertEqual(self.published[name],
                                 QMetaMethod.MethodType.Slot,
                                 f"{name} must stay a Slot")
                mo = self.inst.metaObject()
                for i in range(mo.methodOffset(), mo.methodCount()):
                    m = mo.method(i)
                    if bytes(m.name()).decode() == name:
                        self.assertEqual(
                            len(m.parameterTypes()), len(types),
                            f"{name}: arity drifted "
                            f"({list(m.parameterTypes())} vs {types})")

    def test_R8_class_attributes_are_reexported(self):
        for attr in ("GRID_VERSION", "WINDOW_IDS", "V1_WINDOW_IDS",
                     "MIN_GRID_SIZE", "_default_grid_tree",
                     "_parse_grid_payload", "_canonical_grid_payload",
                     "_migrate_grid_tree"):
            self.assertTrue(hasattr(Bridge, attr), f"missing {attr}")
        for attr in ("COMMAND_KINDS", "UNDO_LABELS", "HISTORY_KINDS",
                     "WORLD_UNDO_KINDS"):
            self.assertTrue(hasattr(Bridge, attr), f"missing {attr}")
        self.assertEqual(Bridge.COMMAND_KINDS, UndoService.COMMAND_KINDS)

    def test_R12_every_js_called_name_exists_on_the_router(self):
        pat = re.compile(r"bridge\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
        called = set()
        for fn in sorted(os.listdir(UI_JS)):
            if fn.endswith(".js"):
                with open(os.path.join(UI_JS, fn), encoding="utf-8") as f:
                    called |= set(pat.findall(f.read()))
        self.assertGreater(len(called), 40, "JS scan sanity")
        missing = sorted(n for n in called if not callable(getattr(self.inst, n, None)))
        self.assertEqual(missing, [], "JS calls dead slots")


class TestForwarding(unittest.TestCase):
    """R-3 / R-10 — slots forward args + return values, exactly once."""

    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        self.engine = FakeEngine()
        self.br = make_bare(engine=self.engine, config=self.world.config)

    def _inject_fake(self, cls, **methods):
        self.br._bridges = {cls.__name__: type("Fake", (), methods)()}
        return self.br._bridges[cls.__name__]

    def test_R3_forwarder_passes_args_verbatim_and_returns_value(self):
        seen = {}

        class FakeLabel:
            def label_create(self, name, color):
                seen["create"] = (name, color)
                return json.dumps({"ok": True, "id": "l1"})

        # single no-arg slot
        self._inject_fake(CdpBridge, get_tabs=lambda *a: "[]")
        self.assertEqual(self.br.get_tabs(), "[]")

        # multi-arg slot: both args arrive in order
        from bridge.label_bridge import LabelBridge
        self._inject_fake(LabelBridge, label_create=FakeLabel().label_create)
        payload = self.br.label_create("work", "#112233")
        self.assertEqual(seen["create"], ("work", "#112233"))
        self.assertEqual(json.loads(payload)["ok"], True)

    def test_R10_slot_routes_to_exactly_one_domain_object(self):
        counts = []
        self._inject_fake(StackBridge,
                          get_stack_json=lambda *a: counts.append(1)
                          or '[{"block_id":"PAUSE"}]')
        self.assertEqual(self.br.get_stack_json(), '[{"block_id":"PAUSE"}]')
        self.assertEqual(len(counts), 1, "slot must forward exactly once")

    def test_R3_write_through_late_config_is_seen(self):
        # R-7: a bare router gets its config AFTER construction (legacy tests)
        seen = {}

        def get_message():
            seen["cfg"] = self.br._ctx.config
            return "hello"

        self._inject_fake(StackBridge, get_message=staticmethod(get_message))
        cfg2 = TempWorld()
        self.addCleanup(cfg2.__exit__, None, None, None)
        self.br._config = cfg2.config
        self.assertIs(self.br._ctx.config, cfg2.config)
        self.assertEqual(self.br.get_message(), "hello")
        self.assertIs(seen["cfg"], cfg2.config)


class TestSignalReEmission(unittest.TestCase):
    """R-4 — domain signals re-emit on the Router."""

    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        self.br = Bridge(config=self.world.config, engine=FakeEngine())

    def test_R4_domain_signal_rereaches_router_once(self):
        rec = Recorder(self.br.stack_complete)
        rec2 = Recorder(self.br.users_updated)
        # domain signal → router signal
        self.br._bridge(StackBridge).stack_complete.emit()
        self.br._bridge(StackBridge).stack_complete.emit()
        self.assertEqual(len(rec.calls), 2, "each emit must re-emit once")

        self.br._bridge(StackBridge).preset_list_updated.emit('[{"n":1}]')
        self.assertEqual(rec.calls, [(), ()],
                         "other signals must not reach stack_complete")
        preset_rec = Recorder(self.br.preset_list_updated)
        self.br._bridge(StackBridge).preset_list_updated.emit("payload-1")
        self.assertEqual(preset_rec.calls, ["payload-1"])

        self.br._bridge(StackBridge).stack_complete.emit()
        self.assertEqual(len(rec.calls), 3, "no duplicate wiring")

    def test_R11_bus_logmessage_reroutes_to_log_message_signal(self):
        rec = Recorder(self.br.log_message)
        from core.events import EventBus, LogMessage
        bus = self.br._ctx.bus
        bus.emit(LogMessage(message="hello-log", level="warning"))
        self.assertEqual(rec.calls, [("hello-log", "warning")])


class TestBuildRobustness(unittest.TestCase):
    """R-5 / R-6 / R-9 — build fails loudly; lazily-built once; subclass."""

    def test_R5_duplicate_signal_name_fails_the_build(self):
        class A(QObject):
            dup = Signal(str)

            def __init__(self, ctx, parent=None):
                QObject.__init__(self, parent)

        class B(QObject):
            dup = Signal(int)

            def __init__(self, ctx, parent=None):
                QObject.__init__(self, parent)

        import bridge.router as router_mod
        saved = list(router_mod.BRIDGE_CLASSES)
        router_mod.BRIDGE_CLASSES = [A, B]
        try:
            with self.assertRaises(ValueError):
                _build_router_class()
        finally:
            router_mod.BRIDGE_CLASSES = saved

    def test_R6_lazy_path_builds_each_domain_bridge_once(self):
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        real = Bridge._bridge

        b1 = Bridge._bridge(br, CdpBridge)
        b2 = Bridge._bridge(br, CdpBridge)
        self.assertIs(b1, b2, "second access must return the SAME bridge")
        self.assertIs(br._bridges["CdpBridge"], b1)

    def test_R9_router_is_subclassable(self):
        class FakeBridge(Bridge):
            def get_message(self):
                return "overridden"

        inst = FakeBridge.__new__(FakeBridge)
        QObject.__init__(inst)
        self.assertEqual(inst.get_message(), "overridden")
        # the wire surface survives subclassing
        self.assertTrue(hasattr(inst, "get_tabs"))
        self.assertTrue(hasattr(inst, "get_undo_history"))


if __name__ == "__main__":
    unittest.main()
